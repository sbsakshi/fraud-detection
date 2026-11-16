"""Create all tables in the configured database (local SQLite dev only).

Postgres deployments use `alembic upgrade head` instead; this is the
equivalent for the zero-install SQLite path in scripts/dev.sh.
"""

from app import models  # noqa: F401  (registers ORM mappers)
from app.db import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print(f"Tables ready at {engine.url}")
