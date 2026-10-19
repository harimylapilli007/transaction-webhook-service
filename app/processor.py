import asyncio
from datetime import datetime, timezone

from app.config import processing_delay_seconds
from app.database import SessionLocal
from app.models import Transaction


async def complete_after_delay(transaction_id: str, delay_seconds: float | None = None) -> None:
    wait_for = processing_delay_seconds() if delay_seconds is None else delay_seconds
    if wait_for > 0:
        await asyncio.sleep(wait_for)
    mark_processed(transaction_id)


def mark_processed(transaction_id: str) -> None:
    db = SessionLocal()
    try:
        txn = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_id == transaction_id,
                Transaction.status == "PROCESSING",
            )
            .one_or_none()
        )
        if txn is None:
            return
        txn.status = "PROCESSED"
        txn.processed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def recover_pending_jobs() -> None:
    delay = processing_delay_seconds()
    db = SessionLocal()
    try:
        pending = db.query(Transaction).filter(Transaction.status == "PROCESSING").all()
        jobs = [(txn.transaction_id, txn.created_at) for txn in pending]
    finally:
        db.close()

    now = datetime.now(timezone.utc)
    for transaction_id, created_at in jobs:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elapsed = (now - created_at).total_seconds()
        remaining = max(0.0, delay - elapsed)
        asyncio.create_task(complete_after_delay(transaction_id, remaining))
