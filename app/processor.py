import asyncio
import logging
from datetime import datetime, timezone

from app.config import processing_delay_seconds
from app.database import SessionLocal
from app.models import Transaction

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 1.0
RETRY_MAX_SECONDS = 60.0

# The event loop only keeps weak references to tasks, so hold them here until done.
_background_tasks: set[asyncio.Task] = set()


def schedule_processing(transaction_id: str, delay_seconds: float | None = None) -> None:
    task = asyncio.create_task(complete_after_delay(transaction_id, delay_seconds))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def complete_after_delay(transaction_id: str, delay_seconds: float | None = None) -> None:
    wait_for = processing_delay_seconds() if delay_seconds is None else delay_seconds
    if wait_for > 0:
        await asyncio.sleep(wait_for)

    # Retry until the result is stored; the row stays PROCESSING meanwhile, and
    # startup recovery picks it up if the process dies first.
    attempt = 0
    while True:
        try:
            await asyncio.to_thread(mark_processed, transaction_id)
            return
        except Exception:
            backoff = min(RETRY_BASE_SECONDS * 2**attempt, RETRY_MAX_SECONDS)
            attempt += 1
            logger.exception(
                "Failed to mark %s processed (attempt %d); retrying in %.1fs",
                transaction_id,
                attempt,
                backoff,
            )
            await asyncio.sleep(backoff)


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
        schedule_processing(transaction_id, remaining)
