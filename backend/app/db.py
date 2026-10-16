from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

SQLALCHEMY_DATABASE_URL = settings.database_url

# SQLite is the zero-install local-dev backend (see scripts/dev.sh); Postgres
# remains the target for docker compose. FastAPI runs sync endpoints on a
# threadpool, and SQLite's default refuses cross-thread connection reuse.
_connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def check_db_connection() -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def get_db():
    """FastAPI dependency: one session per request, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
