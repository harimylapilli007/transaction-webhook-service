import os

from dotenv import load_dotenv

# Local runs read DATABASE_URL from .env; on Render it comes from the dashboard.
load_dotenv()


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Use your Supabase connection string "
            "(Supabase -> Connect -> Session pooler)."
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url.startswith("postgresql://") or "supabase" not in url:
        raise RuntimeError("DATABASE_URL must be a Supabase Postgres connection string.")
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def processing_delay_seconds() -> float:
    return float(os.getenv("PROCESSING_DELAY_SECONDS", "30"))
