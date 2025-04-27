"""
Database connection setup using SQLModel and SQLAlchemy for DuckDB.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import structlog
from sqlalchemy.engine import Engine  # Import Engine type hint
from sqlmodel import Session, SQLModel, create_engine

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
DEFAULT_DB_FILE = DB_DIR / "regulations.db"  # Renamed in previous steps?

# Module-level variable for the engine (initialized later)
_engine: Optional[Engine] = None


def get_db_url(db_file: Path = DEFAULT_DB_FILE) -> str:
    """Constructs the database URL for DuckDB."""
    # Ensure the parent directory exists
    db_file.parent.mkdir(parents=True, exist_ok=True)
    # Use absolute path for consistency
    absolute_db_path = db_file.resolve()
    # Format for duckdb-engine (SQLAlchemy dialect)
    url = f"duckdb:///{absolute_db_path}"
    log.debug(
        "Constructed DB URL", url=url
    )  # Use debug level for potentially sensitive info
    return url


def get_engine(db_file: Path = DEFAULT_DB_FILE) -> Engine:
    """Gets the SQLAlchemy engine, creating it if it doesn't exist."""
    global _engine
    if _engine is None:
        db_url = get_db_url(db_file)
        try:
            # connect_args can be used for DuckDB specific config if needed later
            # e.g., connect_args={"config": {"memory_limit": "500MB"}}
            _engine = create_engine(db_url, echo=False)  # Set echo=True for SQL logging
            log.info("SQLAlchemy engine created.", db_url=db_url)
        except Exception as e:
            log.exception(
                "Failed to create SQLAlchemy engine.", db_url=db_url, error=str(e)
            )
            raise  # Re-raise the exception after logging
    return _engine


def create_db_and_tables(engine: Optional[Engine] = None) -> None:
    """Creates the database and all tables defined in SQLModel models."""
    if engine is None:
        engine = get_engine()
        # Ensure the engine was successfully created
        if engine is None:
            log.error("Engine is None, cannot create tables.")
            return

    log.info("Attempting to create database tables if they don't exist...")
    try:
        # SQLModel.metadata.create_all is idempotent
        SQLModel.metadata.create_all(engine)
        log.info("Database tables ensured.")
    except Exception as e:
        log.exception("Failed to create database tables.", error=str(e))
        raise  # Re-raise to indicate failure


@contextmanager
def get_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    if engine is None:
        engine = get_engine()
        if engine is None:
            log.error("Engine is None, cannot create session.")
            # Raise ValueError consistent with test expectation
            raise ValueError(
                "Database engine is not initialized. Call get_engine first."
            )

    # Note: autocommit=False, autoflush=False are common defaults for Session
    session = Session(engine)
    log.debug("Database session created.")
    try:
        yield session
        session.commit()
        log.debug("Database session committed.")
    except Exception as e:
        log.exception("Exception during database session, rolling back.", error=str(e))
        session.rollback()
        raise  # Re-raise the exception after rollback
    finally:
        session.close()
        log.debug("Database session closed.")


# Example of how to use it
if __name__ == "__main__":  # pragma: no cover
    import datetime  # Add datetime import
    import logging
    import time  # Add time import

    from sqlmodel import select

    # Basic logging setup for direct script execution
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    structlog.configure(
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    log.info("Running SQLModel connection example...")

    try:
        # 1. Ensure DB and tables are created
        current_engine = get_engine()
        create_db_and_tables(current_engine)

        log.info("Creating a new record...")
        # 2. Use the session context manager
        with get_session(current_engine) as session:
            # Create a model instance
            record_to_add = models.FileRecord(
                source_path=f"/example/main_{int(time.time())}.txt",
                filename=f"main_{int(time.time())}.txt",
                blob=b"Content from main block",
                size_bytes=len(b"Content from main block"),
                last_modified_ts=datetime.datetime.now(datetime.timezone.utc),
                extracted_text="# Example Text\nFrom main execution.",
            )
            session.add(record_to_add)
            # Commit happens automatically at the end of the 'with' block
            log.info("Record added (pending commit).", path=record_to_add.source_path)

        log.info("Querying records...")
        # 3. Query records in a new session
        with get_session(current_engine) as session:
            statement = select(models.FileRecord).limit(5)
            results = session.exec(statement).all()
            log.info(f"Found {len(results)} records:")
            for record in results:
                # Explicitly check for None before creating preview
                if record.extracted_text:
                    text_preview = record.extracted_text[:30] + "..."
                else:
                    text_preview = "[None]"
                log.info(
                    "  Record",
                    filename=record.filename,
                    size=record.size_bytes,
                    text_preview=text_preview,
                )

    except Exception as e:
        log.exception(
            "An error occurred during SQLModel connection example.", error=str(e)
        )
