import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Transaction
from app.processor import complete_after_delay, recover_pending_jobs
from app.schemas import TransactionResponse, TransactionWebhook

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
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


@app.post("/v1/webhooks/transactions", status_code=status.HTTP_202_ACCEPTED)
async def receive_transaction(
    payload: TransactionWebhook, db: Session = Depends(get_db)
) -> Response:
    txn = Transaction(
        transaction_id=payload.transaction_id,
        source_account=payload.source_account,
        destination_account=payload.destination_account,
        amount=payload.amount,
        currency=payload.currency,
        status="PROCESSING",
    )
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return Response(status_code=status.HTTP_202_ACCEPTED)

    asyncio.create_task(complete_after_delay(payload.transaction_id))
    return Response(status_code=status.HTTP_202_ACCEPTED)


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
