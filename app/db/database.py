"""Database engine and session factory construction."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


def _ensure_sqlite_directory(database_url: str) -> None:
    database = make_url(database_url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(database_url: str) -> Engine:
    """Create the engine; for SQLite also enable foreign keys and cross-thread use."""
    is_sqlite = make_url(database_url).get_backend_name() == "sqlite"
    if not is_sqlite:
        return create_engine(database_url)

    _ensure_sqlite_directory(database_url)
    # FastAPI runs sync endpoints in a thread pool; each request uses its own session.
    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create tables if they do not exist."""
    Base.metadata.create_all(engine)
