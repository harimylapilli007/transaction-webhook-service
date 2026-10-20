# Transaction Webhook Service

Python service that accepts payment-processor webhooks, acknowledges them immediately (`202 Accepted`), and processes each unique transaction in the background after a 30-second delay.

**Public repo:** [github.com/harimylapilli007/transaction-webhook-service](https://github.com/harimylapilli007/transaction-webhook-service)

**Public API (Render):** [https://transaction-webhook-service-n8fi.onrender.com](https://transaction-webhook-service-n8fi.onrender.com)

**Transactions history UI:** [https://transaction-webhook-service-n8fi.onrender.com/transactions](https://transaction-webhook-service-n8fi.onrender.com/transactions) (local: `http://localhost:8000/transactions`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/` | Health: `{"status":"HEALTHY","current_time":"...Z"}` |
| `GET` | `/transactions` | Transaction history page |
| `POST` | `/v1/webhooks/transactions` | Persist as `PROCESSING`, return `202` within 500ms with `{"message","transaction_id","duplicate"}` |
| `GET` | `/v1/transactions` | Recent history (newest first, max 100) |
| `GET` | `/v1/transactions/{transaction_id}` | One-element JSON array with status and timestamps |

Interactive docs: [https://transaction-webhook-service-n8fi.onrender.com/docs](https://transaction-webhook-service-n8fi.onrender.com/docs)

The free Render instance sleeps when idle. The first request after that can take ~30 seconds. Production data is stored in **Supabase Postgres**.

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

The only database is **Supabase**. Copy `.env.example` to `.env` and set `DATABASE_URL` to your Supabase **Session pooler** connection string (Supabase → Connect → Session pooler). URL-encode special characters in the password (`@` → `%40`). `.env` is gitignored.

The app refuses to start without a Supabase `DATABASE_URL`, adds `sslmode=require`, and creates the `transactions` table on startup.

## Test

Automated (runs against the Supabase database in `.env` with a 1-second delay; test rows use a unique `txn_test_` prefix and are deleted afterwards):

```bash
pip install -r requirements-dev.txt
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
- **Supabase Postgres everywhere** via `DATABASE_URL`, locally and on Render, so there is one database engine and no dev/prod drift. Supabase is used through its Session pooler because the direct connection host is IPv6-only, which Render's free tier can't reach.
- **Persist first, then schedule work.** The webhook writes a `PROCESSING` row and returns. An asyncio task sleeps 30 seconds, then marks the row `PROCESSED` with `processed_at`.
- **History UI at `/transactions`.** A small same-origin page sends test webhooks, shows the raw POST response (status, latency, body), and lists stored webhooks, refreshing so PROCESSING rows update without a separate frontend host.
- **Off-loop DB writes.** The webhook handler runs its insert in a worker thread so a slow database commit never blocks other requests on the event loop.
- **One round trip per webhook.** The insert is a single autocommit `INSERT ... ON CONFLICT (transaction_id) DO NOTHING RETURNING id` on a pre-warmed connection, so the 202 costs one database round trip (~120ms to a remote Supabase region) instead of five. A duplicate returns no row, so it is acknowledged without scheduling a second job.
- **Retry until stored.** If marking a transaction `PROCESSED` fails (e.g. a DB blip), the job retries with exponential backoff (capped at 60s) instead of silently dying. Task references are held until completion so they can't be garbage-collected mid-flight.
- **Money as `Decimal`.** Amounts are validated as positive with at most 2 decimal places and stored as `NUMERIC(18,2)`; currency must be a 3-letter code (normalized to upper case). Invalid payloads get `422`.
- **Startup recovery.** If the process restarts mid-delay, pending `PROCESSING` rows are resumed instead of being lost.

## Deploy (Render)

`render.yaml` defines a Python web service. The database is Supabase.

1. Push this repo to GitHub (public).
2. In Render, New → Blueprint from `render.yaml`, or a Python Web Service with:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Set `DATABASE_URL` to the Supabase **Session pooler** connection string (Environment tab).
4. Set `PROCESSING_DELAY_SECONDS=30`.
