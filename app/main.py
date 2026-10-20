from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import Base, autocommit_engine, engine, get_db
from app.models import Transaction
from app.processor import recover_pending_jobs, schedule_processing
from app.schemas import TransactionResponse, TransactionWebhook

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Open the webhook connection now so the first webhook doesn't pay the TLS handshake.
    with autocommit_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    recover_pending_jobs()
    yield


app = FastAPI(title="Transaction Webhook Service", lifespan=lifespan)


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_record(txn: Transaction) -> dict:
    body = TransactionResponse.model_validate(txn)
    return {
        "transaction_id": body.transaction_id,
        "source_account": body.source_account,
        "destination_account": body.destination_account,
        "amount": float(body.amount),
        "currency": body.currency,
        "status": body.status,
        "created_at": _serialize_dt(body.created_at),
        "processed_at": _serialize_dt(body.processed_at),
    }


@app.get("/transactions", include_in_schema=False)
def transactions_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
@app.get("/health")
def health_check() -> JSONResponse:
    return JSONResponse(
        {
            "status": "HEALTHY",
            "current_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def _insert_if_new(payload: TransactionWebhook) -> bool:
    """Store the webhook as PROCESSING. Returns False if the transaction_id already exists."""
    # One autocommit statement = one DB round trip, which keeps the 202 fast
    # even when the database is in a distant region.
    stmt = (
        insert(Transaction)
        .values(
            transaction_id=payload.transaction_id,
            source_account=payload.source_account,
            destination_account=payload.destination_account,
            amount=payload.amount,
            currency=payload.currency,
            status="PROCESSING",
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["transaction_id"])
        .returning(Transaction.id)
    )
    try:
        with autocommit_engine.connect() as conn:
            return conn.execute(stmt).first() is not None
    except DBAPIError as exc:
        if not exc.connection_invalidated:
            raise
    # The pooled connection was dead (e.g. closed by the server while idle); retry on a fresh one.
    with autocommit_engine.connect() as conn:
        return conn.execute(stmt).first() is not None


@app.post("/v1/webhooks/transactions", status_code=status.HTTP_202_ACCEPTED)
async def receive_transaction(payload: TransactionWebhook) -> JSONResponse:
    # Run the blocking DB write off the event loop so slow commits don't stall other requests.
    is_new = await run_in_threadpool(_insert_if_new, payload)
    if is_new:
        schedule_processing(payload.transaction_id)
    return JSONResponse(
        {
            "message": "Accepted" if is_new else "Already received",
            "transaction_id": payload.transaction_id,
            "duplicate": not is_new,
        },
        status_code=status.HTTP_202_ACCEPTED,
    )


@app.get("/v1/transactions")
def list_transactions(db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(100)
        .all()
    )
    return [_public_record(txn) for txn in rows]


@app.get("/v1/transactions/{transaction_id}")
def get_transaction(transaction_id: str, db: Session = Depends(get_db)) -> list[dict]:
    txn = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).one_or_none()
    if txn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return [_public_record(txn)]
