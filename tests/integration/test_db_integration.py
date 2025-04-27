"""Integration tests for database interactions."""

import datetime
import time  # Import time for potential sleep
import uuid
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy.engine import Engine

# Import components to test integration
from reg_agent.core.db.connection import create_db_and_tables, get_engine
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="function")
def integration_db_path(tmp_path: Path) -> Path:
    """Provides a temporary path for the integration test database."""
    return tmp_path / "integration_test.db"


@pytest.fixture(scope="function")
def db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Provides a clean SQLAlchemy engine for each integration test function."""
    # Ensure clean slate by resetting global engine if it exists
    # (This assumes connection module might have a global _engine variable)
    from reg_agent.core.db import connection as db_connection

    db_connection._sync_engine = None

    # Create engine for this test
    db_file = tmp_path / "integration_test.db"
    engine = get_engine(db_file=db_file)
    assert engine is not None, "Engine creation failed"

    # Create tables
    create_db_and_tables(engine)

    # Add a small delay after creating tables, sometimes helps with file locks
    time.sleep(0.1)

    yield engine  # Provide the engine to the test

    # Teardown: Dispose engine and potentially delete DB file
    engine.dispose()
    db_connection._sync_engine = None  # Reset global state again
    # Add delay before unlinking
    time.sleep(0.1)
    if db_file.exists():
        try:
            db_file.unlink()
        except OSError:
            # Handle potential issues deleting the file (e.g., locks on Windows)
            print(f"Warning: Could not delete test DB: {db_file}")


def test_add_and_retrieve_file_record(db_engine: Engine):
    """Tests adding a record via repository and retrieving it using UoW."""
    record_id = uuid.uuid4()
    source_path = f"/integration/test_{record_id}.pdf"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    record_to_add = FileRecord(
        id=record_id,
        source_path=source_path,
        filename=f"test_{record_id}.pdf",
        blob=b"integration test content",
        extracted_text="# Integration Test\nSome text.",
        size_bytes=24,
        last_modified_ts=timestamp,
        status=FileStatus.PENDING_PROCESS,
    )

    # --- Add record using UoW ---
    try:
        with SqlModelUnitOfWork() as uow:
            uow.documents.add(record_to_add)
        # UoW commits automatically on exit
    except Exception as e:
        pytest.fail(f"Adding record failed with exception: {e}")

    # --- Retrieve and verify record using UoW in a new context ---
    retrieved_record: FileRecord | None = None
    try:
        with SqlModelUnitOfWork() as uow:
            # Use repository get method
            retrieved_record = uow.documents.get(record_id)

            # Perform assertions *inside* the UoW context
            assert retrieved_record is not None, (
                "Record was not found in the database after add."
            )
            assert retrieved_record.id == record_id
            assert retrieved_record.source_path == source_path
            assert retrieved_record.filename == f"test_{record_id}.pdf"
            assert retrieved_record.blob == b"integration test content"
            assert retrieved_record.extracted_text == "# Integration Test\nSome text."
            assert retrieved_record.size_bytes == 24
            assert retrieved_record.status == FileStatus.PENDING_PROCESS

            # --- Timestamp Handling --- #
            # --- last_modified_ts ---
            retrieved_ts = retrieved_record.last_modified_ts
            if retrieved_ts:
                # retrieved_ts_dt = cast(datetime.datetime, retrieved_ts) # Removed cast

                # Convert retrieved timestamp (potentially naive) to aware UTC
                if retrieved_ts.tzinfo is None:
                    # Assume the naive time is local, convert to aware UTC
                    retrieved_ts_aware = retrieved_ts.astimezone(datetime.timezone.utc)
                else:
                    # Already timezone-aware, ensure it's UTC
                    retrieved_ts_aware = retrieved_ts.astimezone(datetime.timezone.utc)

                # Compare rounded timestamps
                timestamp_rounded = timestamp.replace(microsecond=0)
                retrieved_ts_aware_rounded = retrieved_ts_aware.replace(microsecond=0)

                assert retrieved_ts_aware_rounded == timestamp_rounded, (
                    f"Timestamp mismatch: Retrieved (UTC): {retrieved_ts_aware_rounded}, Original: {timestamp_rounded}"
                )
            else:
                pytest.fail("last_modified_ts was None after retrieval, but should not be.")

            # --- created_at / updated_at ---
            created_at = retrieved_record.created_at
            updated_at = retrieved_record.updated_at

            # Convert to aware UTC if necessary
            created_at_aware = (
                created_at.astimezone(datetime.timezone.utc)
                if created_at.tzinfo is None
                else created_at.astimezone(datetime.timezone.utc)
            )
            updated_at_aware = (
                updated_at.astimezone(datetime.timezone.utc)
                if updated_at.tzinfo is None
                else updated_at.astimezone(datetime.timezone.utc)
            )

            # Allow a small difference between creation and update time
            assert abs(updated_at_aware - created_at_aware) < datetime.timedelta(
                seconds=5 # Increased tolerance slightly
            ), f"created_at ({created_at_aware}) and updated_at ({updated_at_aware}) are too far apart"

    except Exception as e:
        pytest.fail(f"Retrieving record or asserting failed with exception: {e}")


def test_exists_by_source_path_integration(db_engine: Engine):
    """Tests the exists_by_source_path method against a real DB using UoW."""
    record_id = uuid.uuid4()
    source_path = f"/integration/exists_test_{record_id}.pdf"
    timestamp = datetime.datetime.now(datetime.timezone.utc)

    record_to_add = FileRecord(
        id=record_id,
        source_path=source_path,
        filename=f"exists_test_{record_id}.pdf",
        blob=b"exists test",
        size_bytes=11,
        last_modified_ts=timestamp,
        status=FileStatus.PENDING_PROCESS,
    )

    # --- Check existence before adding ---
    try:
        with SqlModelUnitOfWork() as uow:
            exists_before = uow.documents.exists_by_source_path(source_path)
    except Exception as e:
        pytest.fail(f"Checking existence (before add) failed with exception: {e}")
    assert exists_before is False, "Record should not exist before being added."

    # --- Add record ---
    try:
        with SqlModelUnitOfWork() as uow:
            uow.documents.add(record_to_add)
    except Exception as e:
        pytest.fail(f"Adding record failed with exception: {e}")

    # --- Check existence after adding ---
    try:
        with SqlModelUnitOfWork() as uow:
            exists_after = uow.documents.exists_by_source_path(source_path)
    except Exception as e:
        pytest.fail(f"Checking existence (after add) failed with exception: {e}")
    assert exists_after is True, "Record should exist after being added."

    # --- Check non-existent path ---
    try:
        with SqlModelUnitOfWork() as uow:
            exists_non_existent = uow.documents.exists_by_source_path("/non/existent/path.txt")
    except Exception as e:
        pytest.fail(f"Checking non-existent path failed with exception: {e}")
    assert exists_non_existent is False, "Non-existent path should return False."


def test_get_records_by_status_integration(db_engine: Engine):
    """Tests retrieving records by status against a real DB using UoW."""
    # Generate unique IDs for each record
    record_id_pending = uuid.uuid4()
    record_id_completed = uuid.uuid4()
    record_id_failed = uuid.uuid4()

    source_path_base = "/integration/status_test"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    record_pending = FileRecord(
        id=record_id_pending,
        source_path=f"{source_path_base}_pending.pdf",
        filename=f"status_test_{record_id_pending}.pdf",
        blob=b"pending content",
        size_bytes=15,
        last_modified_ts=timestamp,
        status=FileStatus.PENDING_PROCESS,
    )

    record_completed = FileRecord(
        id=record_id_completed,
        source_path=f"{source_path_base}_completed.pdf",
        filename=f"status_test_{record_id_completed}.pdf",
        blob=b"completed content",
        size_bytes=17,
        last_modified_ts=timestamp,
        status=FileStatus.COMPLETED,
    )

    record_failed = FileRecord(
        id=record_id_failed,
        source_path=f"{source_path_base}_failed.pdf",
        filename=f"status_test_{record_id_failed}.pdf",
        blob=b"failed content",
        size_bytes=14,
        last_modified_ts=timestamp,
        status=FileStatus.FAILED_OCR,
    )

    # Add records with different statuses using UoW
    try:
        with SqlModelUnitOfWork() as uow:
            uow.documents.add(record_pending)
            uow.documents.add(record_completed)
            uow.documents.add(record_failed)
    except Exception as e:
        pytest.fail(f"Adding records failed with exception: {e}")

    # Retrieve PENDING_PROCESS records using UoW
    retrieved_pending = []
    try:
        with SqlModelUnitOfWork() as uow:
            retrieved_pending = uow.documents.get_records_by_status(
                FileStatus.PENDING_PROCESS
            )
            # Perform assertions while the session is active
            assert len(retrieved_pending) == 1
            # Compare against the stored UUID directly
            assert retrieved_pending[0].id == record_id_pending
            # Check other statuses if needed (optional)
            # retrieved_completed = uow.documents.get_records_by_status(
            #     FileStatus.COMPLETED
            # )
            # assert len(retrieved_completed) == 1
            # assert retrieved_completed[0].id == record_completed.id

    except Exception as e:
        pytest.fail(f"Retrieving PENDING_PROCESS records failed: {e}")

    # Retrieve COMPLETED records using UoW
    retrieved_completed = []
    try:
        with SqlModelUnitOfWork() as uow:
            retrieved_completed = uow.documents.get_records_by_status(
                FileStatus.COMPLETED
            )
            # Perform assertions while the session is active
            assert len(retrieved_completed) == 1
            # Compare against the stored UUID directly
            assert retrieved_completed[0].id == record_id_completed
    except Exception as e:
        pytest.fail(f"Retrieving COMPLETED records failed: {e}")

    # Retrieve FAILED_OCR records using UoW
    retrieved_failed = []
    try:
        with SqlModelUnitOfWork() as uow:
            retrieved_failed = uow.documents.get_records_by_status(
                FileStatus.FAILED_OCR
            )
            # Perform assertions while the session is active
            assert len(retrieved_failed) == 1
            # Compare against the stored UUID directly
            assert retrieved_failed[0].id == record_id_failed
    except Exception as e:
        pytest.fail(f"Retrieving FAILED_OCR records failed: {e}")

    # Optional: Verify counts if needed outside the UoW blocks
    # (Requires careful handling if objects are needed, maybe fetch IDs only)
    # assert len(retrieved_pending) == 1
    # assert len(retrieved_completed) == 1
    # assert len(retrieved_failed) == 1

# Add tests for find_by_metadata and get_distinct_values if not covered elsewhere
# (Assuming they have unit tests, integration might be less critical unless complex JSON involved)
