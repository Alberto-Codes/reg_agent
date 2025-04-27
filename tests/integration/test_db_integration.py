"""Integration tests for database interactions."""

import pytest
import datetime
import uuid
from pathlib import Path
from typing import Generator

from sqlalchemy.engine import Engine

# Import components to test integration
from reg_agent.core.db.connection import get_engine, create_db_and_tables, get_session
from reg_agent.core.db.models import FileRecord
from reg_agent.core.db.repositories import FileRepository

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="function")
def integration_db_path(tmp_path: Path) -> Path:
    """Provides a temporary path for the integration test database."""
    return tmp_path / "integration_test.db"


@pytest.fixture(scope="function")
def db_engine(integration_db_path: Path) -> Generator[Engine, None, None]:
    """Provides a clean SQLAlchemy engine for each integration test function."""
    # Ensure clean slate by resetting global engine if it exists
    # (This assumes connection module might have a global _engine variable)
    from reg_agent.core.db import connection as db_connection

    db_connection._engine = None

    # Create engine for this test
    engine = get_engine(db_file=integration_db_path)
    assert engine is not None, "Engine creation failed"

    # Create tables
    create_db_and_tables(engine)

    yield engine  # Provide the engine to the test

    # Teardown: Dispose engine and potentially delete DB file
    engine.dispose()
    db_connection._engine = None  # Reset global state again
    if integration_db_path.exists():
        try:
            integration_db_path.unlink()
        except OSError:
            # Handle potential issues deleting the file (e.g., locks on Windows)
            print(f"Warning: Could not delete test DB: {integration_db_path}")


def test_add_and_retrieve_file_record(db_engine: Engine):
    """Tests adding a record via repository and retrieving it."""
    record_id = uuid.uuid4()
    source_path = f"/integration/test_{record_id}.pdf"
    timestamp = datetime.datetime.now(datetime.timezone.utc)

    record_to_add = FileRecord(
        id=record_id,
        source_path=source_path,
        filename=f"test_{record_id}.pdf",
        blob=b"integration test content",
        extracted_text="# Integration Test\nSome text.",
        size_bytes=24,
        last_modified_ts=timestamp,
    )

    # --- Add record using repository ---
    try:
        with get_session(engine=db_engine) as session:
            repo = FileRepository(session)
            repo.add(record_to_add)
        # Session commits automatically on exit
    except Exception as e:
        pytest.fail(f"Adding record failed with exception: {e}")

    # --- Retrieve and verify record in a new session ---
    retrieved_record: FileRecord | None = None
    try:
        with get_session(engine=db_engine) as session:
            # Use session.get for direct retrieval by PK
            retrieved_record = session.get(FileRecord, record_id)

            # Perform assertions *inside* the session context
            assert retrieved_record is not None, (
                "Record was not found in the database after add."
            )
            assert retrieved_record.id == record_id
            assert retrieved_record.source_path == source_path
            assert retrieved_record.filename == f"test_{record_id}.pdf"
            assert retrieved_record.blob == b"integration test content"
            assert retrieved_record.extracted_text == "# Integration Test\nSome text."
            assert retrieved_record.size_bytes == 24
            # Compare timestamps carefully (both should now be timezone-aware UTC)
            assert abs(
                retrieved_record.last_modified_ts - timestamp
            ) < datetime.timedelta(seconds=1), (
                f"Timestamp difference too large: {retrieved_record.last_modified_ts} vs {timestamp}"
            )

    except Exception as e:
        pytest.fail(f"Retrieving record or asserting failed with exception: {e}")

    # Final check outside session is less useful due to potential detachment
    # assert retrieved_record is not None


def test_exists_by_source_path_integration(db_engine: Engine):
    """Tests the exists_by_source_path method against a real DB."""
    record_id = uuid.uuid4()
    source_path = f"/integration/exists_{record_id}.txt"
    timestamp = datetime.datetime.now(datetime.timezone.utc)

    record_to_add = FileRecord(
        id=record_id,
        source_path=source_path,
        filename=f"exists_{record_id}.txt",
        blob=b"exists test",
        size_bytes=11,
        last_modified_ts=timestamp,
    )

    # --- Check existence before adding ---
    try:
        with get_session(engine=db_engine) as session:
            repo = FileRepository(session)
            exists_before = repo.exists_by_source_path(source_path)
    except Exception as e:
        pytest.fail(f"Checking existence (before add) failed with exception: {e}")
    assert exists_before is False, "Record should not exist before being added."

    # --- Add record ---
    try:
        with get_session(engine=db_engine) as session:
            repo = FileRepository(session)
            repo.add(record_to_add)
    except Exception as e:
        pytest.fail(f"Adding record failed with exception: {e}")

    # --- Check existence after adding ---
    try:
        with get_session(engine=db_engine) as session:
            repo = FileRepository(session)
            exists_after = repo.exists_by_source_path(source_path)
    except Exception as e:
        pytest.fail(f"Checking existence (after add) failed with exception: {e}")
    assert exists_after is True, "Record should exist after being added."

    # --- Check non-existent path ---
    try:
        with get_session(engine=db_engine) as session:
            repo = FileRepository(session)
            exists_nonexistent = repo.exists_by_source_path("/non/existent/path.nada")
    except Exception as e:
        pytest.fail(f"Checking non-existent path failed with exception: {e}")
    assert exists_nonexistent is False, "Non-existent path should return False."
