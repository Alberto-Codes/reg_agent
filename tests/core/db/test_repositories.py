"""
Unit tests for the repository classes.
"""

import datetime
import uuid
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

# Modules/Classes to test
from reg_agent.core.db import models
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository

# Configure structlog for testing (if capturing logs)
# structlog.configure(processors=[structlog.testing.LogCapture()])


@pytest.fixture
def mock_session() -> MagicMock:
    """Provides a mock SQLModel Session."""
    # Create a MagicMock instance that simulates the Session
    session = MagicMock(spec=Session)
    # Mock the .exec() method chain
    mock_exec = MagicMock()
    session.exec.return_value = mock_exec
    # Set default return values for common methods (can be overridden in tests)
    mock_exec.first.return_value = None
    mock_exec.one_or_none.return_value = None
    mock_exec.all.return_value = []
    return session


@pytest.fixture
def file_repository(mock_session: MagicMock) -> FileRepository:
    """Provides a FileRepository instance with a mock session."""
    return FileRepository(session=mock_session)


@pytest.fixture
def sample_file_record() -> models.FileRecord:
    """Provides a sample FileRecord for testing."""
    return models.FileRecord(
        id=uuid.uuid4(),  # Generate a real UUID
        source_path="/test/path/sample.pdf",
        filename="sample.pdf",
        blob=b"sample content",
        extracted_text="Sample text",
        size_bytes=14,
        last_modified_ts=datetime.datetime.now(datetime.timezone.utc),
    )


def test_repository_init(mock_session: MagicMock):
    """Tests FileRepository initialization."""
    repo = FileRepository(session=mock_session)
    assert repo.session is mock_session


def test_add_success(
    file_repository: FileRepository,
    mock_session: MagicMock,
    sample_file_record: models.FileRecord,
):
    """Tests successfully adding a record."""
    file_repository.add(sample_file_record)
    # Verify that session.add was called exactly once with the sample record
    mock_session.add.assert_called_once_with(sample_file_record)


def test_add_failure(
    file_repository: FileRepository,
    mock_session: MagicMock,
    sample_file_record: models.FileRecord,
):
    """Tests handling of exception during add."""
    # Configure the mock session.add to raise an exception
    mock_session.add.side_effect = Exception("DB Error")

    # Assert that the repository re-raises the exception
    with pytest.raises(Exception, match="DB Error"):
        file_repository.add(sample_file_record)

    mock_session.add.assert_called_once_with(sample_file_record)


def test_exists_by_source_path_found(
    file_repository: FileRepository,
    mock_session: MagicMock,
    sample_file_record: models.FileRecord,
):
    """Tests exists_by_source_path when the record is found."""
    test_path = sample_file_record.source_path
    # Configure the mock session chain to return the sample record
    mock_session.exec.return_value.first.return_value = sample_file_record

    exists = file_repository.exists_by_source_path(test_path)

    assert exists is True
    # Verify that session.exec(select(...)).first() was called
    # We might need more specific assertion on the statement if necessary
    mock_session.exec.assert_called_once()
    mock_session.exec.return_value.first.assert_called_once()


def test_exists_by_source_path_not_found(
    file_repository: FileRepository, mock_session: MagicMock
):
    """Tests exists_by_source_path when the record is not found."""
    test_path = "/non/existent/path.txt"
    # Ensure the mock session chain returns None (default in fixture, but explicit here)
    mock_session.exec.return_value.first.return_value = None

    exists = file_repository.exists_by_source_path(test_path)

    assert exists is False
    mock_session.exec.assert_called_once()
    mock_session.exec.return_value.first.assert_called_once()


def test_exists_by_source_path_failure(
    file_repository: FileRepository, mock_session: MagicMock
):
    """Tests handling of exception during exists_by_source_path."""
    test_path = "/error/path.txt"
    # Configure the mock session.exec to raise an exception
    mock_session.exec.side_effect = Exception("Query Error")

    # Assert that the repository re-raises the exception
    with pytest.raises(Exception, match="Query Error"):
        file_repository.exists_by_source_path(test_path)

    # Verify exec was called
    mock_session.exec.assert_called_once()


def test_get_records_by_status_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    # Dummy records to be returned
    records = [
        FileRecord(
            id=uuid.uuid4(), source_path="/p1.txt", status=FileStatus.PENDING_PROCESS
        ),
        FileRecord(
            id=uuid.uuid4(), source_path="/p2.txt", status=FileStatus.PENDING_PROCESS
        ),
    ]
    # Mock session.exec(...).all() to return the dummy records
    mock_result = MagicMock()
    mock_result.all.return_value = records
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_by_status(FileStatus.PENDING_PROCESS)

    assert found_records == records
    mock_session.exec.assert_called_once()  # Verify query execution
    # Optionally, check the statement passed to exec if needed, but can be complex


def test_get_records_by_status_not_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    # Mock session.exec(...).all() to return an empty list
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_by_status(FileStatus.COMPLETED)

    assert found_records == []
    mock_session.exec.assert_called_once()


def test_get_records_by_status_failure(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    mock_session.exec.side_effect = Exception("DB Query Error")
    with pytest.raises(Exception, match="DB Query Error"):
        repo.get_records_by_status(FileStatus.FAILED_OCR)
    mock_session.exec.assert_called_once()


# --- Tests for get_records_needing_ocr ---


def test_get_records_needing_ocr_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    records = [
        FileRecord(id=uuid.uuid4(), source_path="/no_text1.txt", extracted_text=None),
        FileRecord(id=uuid.uuid4(), source_path="/no_text2.pdf", extracted_text=None),
    ]
    mock_result = MagicMock()
    mock_result.all.return_value = records
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_needing_ocr()

    assert found_records == records
    mock_session.exec.assert_called_once()
    # Could add more specific checks on the select statement if needed


def test_get_records_needing_ocr_not_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_needing_ocr()

    assert found_records == []
    mock_session.exec.assert_called_once()


def test_get_records_needing_ocr_failure(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    mock_session.exec.side_effect = Exception("DB Query Error for OCR")
    with pytest.raises(Exception, match="DB Query Error for OCR"):
        repo.get_records_needing_ocr()
    mock_session.exec.assert_called_once()


# --- Tests for get_records_needing_metadata ---


def test_get_records_needing_metadata_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    records = [
        FileRecord(
            id=uuid.uuid4(),
            source_path="/needs_meta1.txt",
            extracted_text="text",
            meta_data=None,
        ),
        FileRecord(
            id=uuid.uuid4(),
            source_path="/needs_meta2.pdf",
            extracted_text="more text",
            meta_data=None,
        ),
    ]
    mock_result = MagicMock()
    mock_result.all.return_value = records
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_needing_metadata()

    assert found_records == records
    mock_session.exec.assert_called_once()


def test_get_records_needing_metadata_not_found(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.exec.return_value = mock_result

    found_records = repo.get_records_needing_metadata()

    assert found_records == []
    mock_session.exec.assert_called_once()


def test_get_records_needing_metadata_failure(mock_session: MagicMock):
    repo = FileRepository(mock_session)
    mock_session.exec.side_effect = Exception("DB Query Error for Metadata")
    with pytest.raises(Exception, match="DB Query Error for Metadata"):
        repo.get_records_needing_metadata()
    mock_session.exec.assert_called_once()
