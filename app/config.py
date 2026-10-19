import os


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./data/transactions.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if "render.com" in url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def processing_delay_seconds() -> float:
    return float(os.getenv("PROCESSING_DELAY_SECONDS", "30"))
