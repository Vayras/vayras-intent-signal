from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_size=16,
    max_overflow=8,
    pool_timeout=15,
    future=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Add columns create_all will not add to an existing SQLite file."""
    statements = [
        "ALTER TABLE leads ADD COLUMN quality VARCHAR(32) DEFAULT 'unset'",
        "ALTER TABLE leads ADD COLUMN reviewed_at DATETIME",
        "ALTER TABLE leads ADD COLUMN confidence INTEGER DEFAULT 0",
        "ALTER TABLE leads ADD COLUMN reasoning TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN critique TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN similar_cases TEXT DEFAULT '[]'",
    ]
    with engine.begin() as conn:
        for statement in statements:
            try:
                conn.execute(text(statement))
            except Exception:
                continue
