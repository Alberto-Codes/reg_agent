"""
Database connection setup using SQLModel and SQLAlchemy for DuckDB.
"""

from contextlib import contextmanager # Use sync contextmanager
from pathlib import Path
from typing import Generator, Optional # Use sync Generator

import structlog
from sqlalchemy.engine import Engine
# from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker # No longer needed
from sqlmodel import Session, SQLModel, create_engine # Use sync Session and create_engine

# Import the models so SQLModel knows about them for table creation
from reg_agent.core.db import (
    models,  # noqa: F401 (Import models implicitly registers them)
)

log = structlog.get_logger()

# Define the root directory of the project
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
# Define the path to the database directory
DB_DIR = PROJECT_ROOT / "db"
# Define the default database file name
DEFAULT_DB_FILE = DB_DIR / "regulations.db"

# Module-level variable for the sync engine
_sync_engine: Optional[Engine] = None
# Remove async session maker
# _async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None

def get_db_url(db_file: Path = DEFAULT_DB_FILE) -> str:
    """Constructs the database URL for DuckDB."""
    db_file.parent.mkdir(parents=True, exist_ok=True)
    absolute_db_path = db_file.resolve()
    url = f"duckdb:///{absolute_db_path}"
    log.debug("Constructed DB URL", url=url)
    return url

def get_engine(db_file: Path = DEFAULT_DB_FILE) -> Engine:
    """Gets the SQLAlchemy synchronous engine."""
    global _sync_engine
    if _sync_engine is None:
        db_url = get_db_url(db_file)
        try:
            _sync_engine = create_engine(db_url, echo=False)
            log.info("SQLAlchemy sync engine created.", db_url=db_url)
        except Exception as e:
            log.exception(
                "Failed to create SQLAlchemy sync engine.", db_url=db_url, error=str(e)
            )
            raise
    return _sync_engine

def create_db_and_tables(engine: Optional[Engine] = None) -> None:
    """Creates the database and all tables defined in SQLModel models using sync engine."""
    sync_engine = engine or get_engine()
    if sync_engine is None:
        log.error("Sync engine is None, cannot create tables.")
        return
    log.info("Attempting to create database tables if they don't exist...")
    try:
        SQLModel.metadata.create_all(sync_engine)
        log.info("Database tables ensured.")
    except Exception as e:
        log.exception("Failed to create database tables.", error=str(e))
        raise

# Revert to synchronous context manager
@contextmanager
def get_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations (synchronous)."""
    current_engine = engine or get_engine()
    if current_engine is None:
         raise RuntimeError("Sync engine not initialized.")

    # Use standard sync Session
    session = Session(current_engine)
    log.debug("Sync database session created.")
    try:
        yield session
        # Use standard sync commit/rollback
        session.commit()
        log.debug("Sync database session committed.")
    except Exception as e:
        log.exception("Exception during sync database session, rolling back.", error=str(e))
        session.rollback()
        raise # Re-raise the exception after rollback
    finally:
         session.close()
         log.debug("Sync database session closed.")

# Revert example to synchronous
if __name__ == "__main__":  # pragma: no cover
    import time
    import datetime
    from sqlmodel import select # Use sync select

    log.info("Running SYNC SQLModel connection example...")
    try:
        # 1. Ensure DB and tables are created (uses sync engine)
        sync_engine = get_engine()
        create_db_and_tables(sync_engine)

        log.info("Creating a new record using sync session...")
        # 2. Use the sync session context manager
        with get_session(sync_engine) as session:
            record_to_add = models.FileRecord(
                source_path=f"/example/sync_{int(time.time())}.txt",
                filename=f"sync_{int(time.time())}.txt",
                blob=b"Content from sync main block",
                size_bytes=len(b"Content from sync main block"),
                last_modified_ts=datetime.datetime.now(datetime.timezone.utc),
                extracted_text="# Example Sync Text\nFrom sync main execution.",
                status=models.FileStatus.PENDING_PROCESS
            )
            session.add(record_to_add)
            log.info("Record added (sync session - pending commit).", path=record_to_add.source_path)
            # Commit happens automatically via with block exit

        log.info("Querying records using sync session...")
        # 3. Query records in a new sync session
        with get_session(sync_engine) as session:
            statement = select(models.FileRecord).limit(5)
            # Use sync execute
            results = session.exec(statement).all()
            log.info(f"Found {len(results)} records:")
            for record in results:
                text_preview = (record.extracted_text[:30] + "...") if record.extracted_text else "[None]"
                log.info(
                    "  Record",
                    filename=record.filename,
                    size=record.size_bytes,
                    text_preview=text_preview,
                    status=record.status
                )
    except Exception as e:
        log.exception("Error during sync connection example", error=str(e))
