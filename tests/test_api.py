import os
import time

os.environ["DATABASE_URL"] = "sqlite:///./data/test_transactions.db"
os.environ["PROCESSING_DELAY_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

PAYLOAD = {
    "transaction_id": "txn_abc123def456",
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

        pending = client.get("/v1/transactions/txn_abc123def456")
        assert pending.status_code == 200
        records = pending.json()
        assert len(records) == 1
        assert records[0]["status"] == "PROCESSING"
        assert records[0]["processed_at"] is None

        time.sleep(1.3)

        done = client.get("/v1/transactions/txn_abc123def456")
        records = done.json()
        assert len(records) == 1
        assert records[0]["status"] == "PROCESSED"
        assert records[0]["processed_at"] is not None
        assert records[0]["amount"] == 1500
        assert records[0]["currency"] == "INR"


def test_webhook_responds_quickly():
    payload = {**PAYLOAD, "transaction_id": "txn_perf_1"}
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.post("/v1/webhooks/transactions", json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 202
        assert elapsed_ms < 500
