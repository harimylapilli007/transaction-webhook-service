# Transaction Webhook Service

Python service that accepts payment-processor webhooks, acknowledges them immediately (`202 Accepted`), and processes each unique transaction in the background after a 30-second delay.

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

SQLite is used by default (`./data/transactions.db`). To use the existing Supabase Postgres database:

```powershell
$env:DATABASE_URL = "postgresql://postgres:Anilhari@123@db.cxhctqkdrkdzklyiiapy.supabase.co:5432/postgres"
uvicorn app.main:app --reload --port 8000
```

Replace `YOUR-PASSWORD` with the database password from Supabase → Project Settings → Database. The app adds `sslmode=require` automatically for Supabase URLs.

## Test

```bash
pytest -q
```

Manual checks:

```bash
# Health
curl http://localhost:8000/

# Ingest webhook (must return 202 quickly)
curl -i -X POST http://localhost:8000/v1/webhooks/transactions ^
  -H "Content-Type: application/json" ^
  -d "{\"transaction_id\":\"txn_abc123def456\",\"source_account\":\"acc_user_789\",\"destination_account\":\"acc_merchant_456\",\"amount\":1500,\"currency\":\"INR\"}"

# Status while processing
curl http://localhost:8000/v1/transactions/txn_abc123def456

# Wait ~30s, then query again. status should be PROCESSED.
```

Duplicate `transaction_id` values still return `202` and do not create a second row or a second processing job.

## API

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/` | Health check. `{"status":"HEALTHY","current_time":"...Z"}` |
| `POST` | `/v1/webhooks/transactions` | Persist as `PROCESSING`, return `202` within 500ms |
| `GET` | `/v1/transactions/{transaction_id}` | Returns a one-element array with status and timestamps |

## Technical choices

- **FastAPI + Uvicorn** for a small, fast HTTP layer that can accept webhooks without waiting on the 30s simulated processor.
- **SQLAlchemy** with a unique constraint on `transaction_id` for persistence and idempotency. Concurrent duplicates fail the insert and are treated as already accepted.
- **SQLite locally, Postgres in the cloud** via `DATABASE_URL` so the same code runs on a laptop and on Render/Neon/Railway.
- **Persist first, then schedule work.** The webhook writes a `PROCESSING` row and returns. An asyncio task sleeps 30 seconds, then marks the row `PROCESSED` with `processed_at`.
- **Startup recovery.** If the process restarts mid-delay, pending `PROCESSING` rows are resumed instead of being lost.

## Deploy (Render)

Uses the existing Supabase database. Do **not** create a Render Postgres instance.

1. Push this repo to GitHub (public).
2. In Render, New → Blueprint from `render.yaml`, or a Python Web Service with:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Set environment variables:
   - `DATABASE_URL` = `postgresql://postgres:YOUR-PASSWORD@db.cxhctqkdrkdzklyiiapy.supabase.co:5432/postgres` (same password as local)
   - `PROCESSING_DELAY_SECONDS=30`
4. In Supabase → Authentication is not required; allow the Render egress IPs if you enabled network restrictions. Database password goes only in Render env vars, never in git.

The public health endpoint is `GET https://<your-service>.onrender.com/`.
The webhook endpoint is `POST https://<your-service>.onrender.com/v1/webhooks/transactions`.
