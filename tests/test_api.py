# Runs against the Supabase database from DATABASE_URL (.env). Every row this suite
# creates uses a per-run prefix and is deleted at the end, so real data is untouched.
import asyncio
import os
import time
import uuid

os.environ["PROCESSING_DELAY_SECONDS"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import processor  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Transaction  # noqa: E402

RUN = f"txn_test_{uuid.uuid4().hex[:8]}"


def tid(name: str) -> str:
    return f"{RUN}_{name}"


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_rows():
    yield
    db = SessionLocal()
    try:
        db.query(Transaction).filter(Transaction.transaction_id.like(f"{RUN}_%")).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


PAYLOAD = {
    "transaction_id": tid("main"),
    "source_account": "acc_user_789",
    "destination_account": "acc_merchant_456",
    "amount": 1500,
    "currency": "INR",
}


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "HEALTHY"
        assert "current_time" in body


def test_webhook_is_idempotent_and_processes_in_background():
    with TestClient(app) as client:
        first = client.post("/v1/webhooks/transactions", json=PAYLOAD)
        second = client.post("/v1/webhooks/transactions", json=PAYLOAD)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json() == {
            "message": "Accepted",
            "transaction_id": PAYLOAD["transaction_id"],
            "duplicate": False,
        }
        assert second.json()["duplicate"] is True

        pending = client.get(f"/v1/transactions/{PAYLOAD['transaction_id']}")
        assert pending.status_code == 200
        records = pending.json()
        assert len(records) == 1
        assert records[0]["status"] == "PROCESSING"
        assert records[0]["processed_at"] is None

        time.sleep(1.3)

        done = client.get(f"/v1/transactions/{PAYLOAD['transaction_id']}")
        records = done.json()
        assert len(records) == 1
        assert records[0]["status"] == "PROCESSED"
        assert records[0]["processed_at"] is not None
        assert records[0]["amount"] == 1500
        assert records[0]["currency"] == "INR"


def test_transaction_history_list_and_ui():
    payload = {**PAYLOAD, "transaction_id": tid("history")}
    with TestClient(app) as client:
        ui = client.get("/transactions")
        assert ui.status_code == 200
        assert "Transaction history" in ui.text

        assert client.post("/v1/webhooks/transactions", json=payload).status_code == 202
        history = client.get("/v1/transactions")
        assert history.status_code == 200
        mine = [r for r in history.json() if r["transaction_id"] == payload["transaction_id"]]
        assert len(mine) == 1
        assert mine[0]["status"] == "PROCESSING"


def test_webhook_responds_quickly():
    payload = {**PAYLOAD, "transaction_id": tid("perf")}
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.post("/v1/webhooks/transactions", json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 202
        assert elapsed_ms < 500


def test_webhook_rejects_invalid_amount_and_currency():
    with TestClient(app) as client:
        for bad in (
            {**PAYLOAD, "transaction_id": tid("bad1"), "amount": -5},
            {**PAYLOAD, "transaction_id": tid("bad2"), "amount": 0},
            {**PAYLOAD, "transaction_id": tid("bad3"), "amount": 1.234},
            {**PAYLOAD, "transaction_id": tid("bad4"), "currency": "RUPEES"},
        ):
            assert client.post("/v1/webhooks/transactions", json=bad).status_code == 422


def test_decimal_amount_round_trips():
    payload = {**PAYLOAD, "transaction_id": tid("decimal"), "amount": 150.50, "currency": "usd"}
    with TestClient(app) as client:
        assert client.post("/v1/webhooks/transactions", json=payload).status_code == 202
        record = client.get(f"/v1/transactions/{tid('decimal')}").json()[0]
        assert record["amount"] == 150.5
        assert record["currency"] == "USD"


def test_processing_retries_after_db_failure(monkeypatch):
    calls = []

    def flaky_mark_processed(transaction_id):
        calls.append(transaction_id)
        if len(calls) < 3:
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(processor, "mark_processed", flaky_mark_processed)
    monkeypatch.setattr(processor, "RETRY_BASE_SECONDS", 0.01)
    asyncio.run(processor.complete_after_delay("txn_retry_1", 0))
    assert calls == ["txn_retry_1"] * 3
