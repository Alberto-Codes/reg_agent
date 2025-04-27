"""
Unit tests for the repository classes.
"""

import datetime
import uuid
from typing import Generator
from datetime import timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

# Modules/Classes to test
from reg_agent.core.db import models
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import DocumentRepository

# Configure structlog for testing (if capturing logs)
# structlog.configure(processors=[structlog.testing.LogCapture()])


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Creates a clean in-memory SQLite database session for each test."""
    # Use in-memory DuckDB for testing
    engine = create_engine("duckdb:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    # Tables are dropped implicitly when the in-memory DB is closed


@pytest.fixture(name="repo")
def repo_fixture(session: Session) -> DocumentRepository:
    """Provides a DocumentRepository instance initialized with the test session."""
    return DocumentRepository(session=session)


def create_test_record(
    source_path: str = "/test/file.txt",
    status: FileStatus = FileStatus.PENDING_PROCESS,
    extracted_text: str | None = None,
    meta_data: dict | None = None,
    record_id: uuid.UUID | None = None, # Allow specifying ID for testing get_by_id
) -> FileRecord:
    """Helper function to create a FileRecord with defaults."""
    return FileRecord(
        id=record_id or uuid.uuid4(),
        source_path=source_path,
        filename=source_path.split("/")[-1],
        blob=b"test content",
        size_bytes=len(b"test content"),
        last_modified_ts=datetime.datetime.now(timezone.utc),
        extracted_text=extracted_text,
        meta_data=meta_data,
        status=status,
    )


def test_add_record(session: Session, repo: DocumentRepository):
    """Test adding a record successfully."""
    record = create_test_record(source_path="/add/test.txt")
    repo.add(record)
    session.commit()  # Commit needed as repo.add only adds to session

    # Verify record was added by retrieving it
    added_record = session.get(FileRecord, record.id)
    assert added_record is not None
    assert added_record.id == record.id
    assert added_record.source_path == "/add/test.txt"


def test_get_by_id_exists(session: Session, repo: DocumentRepository):
    """Test retrieving an existing record by ID."""
    record_id = uuid.uuid4()
    record = create_test_record(record_id=record_id, source_path="/get/exists.txt")
    session.add(record) # Add directly to session for setup
    session.commit()

    retrieved_record = repo.get_by_id(record_id)

    assert retrieved_record is not None
    assert retrieved_record.id == record_id
    assert retrieved_record.source_path == "/get/exists.txt"


def test_get_by_id_not_exists(repo: DocumentRepository):
    """Test retrieving a non-existent record by ID returns None."""
    non_existent_id = uuid.uuid4()
    retrieved_record = repo.get_by_id(non_existent_id)
    assert retrieved_record is None


def test_exists_by_source_path_true(session: Session, repo: DocumentRepository):
    """Test checking existence for a path that exists."""
    source_path = "/exists/true.txt"
    record = create_test_record(source_path=source_path)
    session.add(record)
    session.commit()

    assert repo.exists_by_source_path(source_path) is True


def test_exists_by_source_path_false(repo: DocumentRepository):
    """Test checking existence for a path that does not exist."""
    source_path = "/exists/false.txt"
    assert repo.exists_by_source_path(source_path) is False


def test_get_records_by_status(session: Session, repo: DocumentRepository):
    """Test retrieving records based on their status."""
    rec1 = create_test_record(source_path="/status/1.txt", status=FileStatus.COMPLETED)
    rec2 = create_test_record(source_path="/status/2.txt", status=FileStatus.PENDING_PROCESS)
    rec3 = create_test_record(source_path="/status/3.txt", status=FileStatus.COMPLETED)
    session.add_all([rec1, rec2, rec3])
    session.commit()

    completed_records = repo.get_records_by_status(FileStatus.COMPLETED)
    pending_records = repo.get_records_by_status(FileStatus.PENDING_PROCESS)
    failed_records = repo.get_records_by_status(FileStatus.FAILED_OCR)

    assert len(completed_records) == 2
    assert {rec.id for rec in completed_records} == {rec1.id, rec3.id}
    assert len(pending_records) == 1
    assert pending_records[0].id == rec2.id
    assert len(failed_records) == 0


# --- Tests for JSON Metadata Methods ---

def test_find_by_metadata_found(session: Session, repo: DocumentRepository):
    """Test finding records using metadata filters."""
    meta1 = {"author": "Alice", "year": 2023, "topic": "db"}
    meta2 = {"author": "Bob", "year": 2024, "topic": "db"}
    meta3 = {"author": "Alice", "year": 2024, "topic": "ai"}

    rec1 = create_test_record(source_path="/meta/1.txt", meta_data=meta1)
    rec2 = create_test_record(source_path="/meta/2.txt", meta_data=meta2)
    rec3 = create_test_record(source_path="/meta/3.txt", meta_data=meta3)
    session.add_all([rec1, rec2, rec3])
    session.commit()

    # Test single filter
    results_author_alice = repo.find_by_metadata({"author": "Alice"})
    assert len(results_author_alice) == 2
    assert {rec.id for rec in results_author_alice} == {rec1.id, rec3.id}

    # Test multiple filters (AND)
    results_alice_2024 = repo.find_by_metadata({"author": "Alice", "year": 2024})
    assert len(results_alice_2024) == 1
    assert results_alice_2024[0].id == rec3.id

    # Test filter matching numeric value (stored as string in comparison)
    results_year_2023 = repo.find_by_metadata({"year": 2023})
    assert len(results_year_2023) == 1
    assert results_year_2023[0].id == rec1.id

    # Test filter resulting in no matches
    results_no_match = repo.find_by_metadata({"topic": "cloud", "author": "Alice"})
    assert len(results_no_match) == 0

    # Test empty filter (should return all records with meta_data, technically)
    # Current implementation returns all records if filters dict is empty
    results_empty_filter = repo.find_by_metadata({})
    assert len(results_empty_filter) == 3
    assert {rec.id for rec in results_empty_filter} == {rec1.id, rec2.id, rec3.id}

def test_find_by_metadata_not_found(repo: DocumentRepository):
    """Test finding records by metadata when no records have metadata."""
    results = repo.find_by_metadata({"author": "Nobody"})
    assert len(results) == 0

# TODO: Add tests for get_records_needing_ocr, get_records_needing_metadata
# TODO: Add tests for find_by_metadata (more edge cases?), get_distinct_values, get_queryable_fields once implemented
