# Transaction Webhook Service

Python service that accepts payment-processor webhooks, acknowledges them immediately (`202 Accepted`), and processes each unique transaction in the background after a 30-second delay.

**Public repo:** [github.com/harimylapilli007/transaction-webhook-service](https://github.com/harimylapilli007/transaction-webhook-service)

**Public API (Render):** [https://transaction-webhook-service-n8fi.onrender.com](https://transaction-webhook-service-n8fi.onrender.com)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/` | Health: `{"status":"HEALTHY","current_time":"...Z"}` |
| `POST` | `/v1/webhooks/transactions` | Persist as `PROCESSING`, return `202` within 500ms |
| `GET` | `/v1/transactions/{transaction_id}` | One-element JSON array with status and timestamps |

Interactive docs: [https://transaction-webhook-service-n8fi.onrender.com/docs](https://transaction-webhook-service-n8fi.onrender.com/docs)

The free Render instance sleeps when idle. The first request after that can take ~30 seconds. Production data is **Render Postgres** (`transaction-webhook-db`). There is no public HTTP URL for the database.

## Run locally

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

SQLite is used by default (`./data/transactions.db`). To use Render Postgres from your laptop, copy the **External Database URL** from the Render dashboard Connections tab (never commit it):

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST.oregon-postgres.render.com/DBNAME"
uvicorn app.main:app --reload --port 8000
```

The app adds `sslmode=require` for Render URLs.

## Test

Automated (uses SQLite and a 1-second delay):

```bash
pytest -q
```

Manual checks against **localhost** (Windows: use `curl.exe`):

```bash
curl http://localhost:8000/

curl -i -X POST http://localhost:8000/v1/webhooks/transactions ^
  -H "Content-Type: application/json" ^
  -d "{\"transaction_id\":\"txn_abc123def456\",\"source_account\":\"acc_user_789\",\"destination_account\":\"acc_merchant_456\",\"amount\":1500,\"currency\":\"INR\"}"

curl http://localhost:8000/v1/transactions/txn_abc123def456
```

Wait ~30 seconds and GET again. `status` should be `PROCESSED`.

Against the **public** API, replace the host with `https://transaction-webhook-service-n8fi.onrender.com` and use a new `transaction_id`. Duplicate `transaction_id` values still return `202` and do not create a second row or a second processing job.

## Technical choices

- **FastAPI + Uvicorn** for a small HTTP layer that can accept webhooks without waiting on the 30s simulated processor.
- **SQLAlchemy** with a unique constraint on `transaction_id` for persistence and idempotency. Concurrent duplicates fail the insert and are treated as already accepted.
- **SQLite locally, Render Postgres in production** via `DATABASE_URL` so the same code runs on a laptop and on Render.
- **Persist first, then schedule work.** The webhook writes a `PROCESSING` row and returns. An asyncio task sleeps 30 seconds, then marks the row `PROCESSED` with `processed_at`.
- **Startup recovery.** If the process restarts mid-delay, pending `PROCESSING` rows are resumed instead of being lost.

## Deploy (Render)

`render.yaml` defines a Python web service and a Render Postgres instance named `transaction-webhook-db`. `DATABASE_URL` is taken from that database.

1. Push this repo to GitHub (public).
2. In Render, New → Blueprint from `render.yaml`, or a Python Web Service with:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Attach `transaction-webhook-db` (or let the Blueprint create it).
4. Set `PROCESSING_DELAY_SECONDS=30`.
