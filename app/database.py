from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import database_url

url = database_url()

engine = create_engine(url, pool_pre_ping=True)
# Hot path for the webhook insert: autocommit and no pre-ping, so one statement costs
# exactly one DB round trip. Callers retry once if a pooled connection went stale.
autocommit_engine = create_engine(url, isolation_level="AUTOCOMMIT", pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
