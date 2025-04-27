# tests/pipelines/ingestion/tasks/test_task_3_metadata.py

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
# from sqlalchemy.engine import Engine # Removed
# from sqlmodel import Session # Removed

from reg_agent.core.db.models import FileRecord, FileStatus

# Keep this for type hinting the mock repository
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import (
    MetadataExtractionService,
    run_task_3,
)

# Import UoW for type hinting the mock
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork
from reg_agent.schemas.metadata import RegulationDocumentMetadata

# --- Fixtures ---


@pytest.fixture
def mock_metadata_service(mocker) -> MagicMock:
    """Mocks the MetadataExtractionService and its async methods."""
    # Mock the service instance returned by the constructor
    mock_service_instance = mocker.MagicMock(spec=MetadataExtractionService)

    # Mock the async extract_metadata method
    dummy_metadata = RegulationDocumentMetadata(
        document_type="Test Doc",
        issuing_agency="Test Agency",
        subject_institution="Test Bank",
        document_identifier="Test-123",
        summary="Test summary.",
        key_topics=["Topic A"],
        action_items=[],
    )
    mock_service_instance.extract_metadata = AsyncMock(return_value=dummy_metadata)

    # Patch the constructor to return our mocked instance
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService",
        return_value=mock_service_instance,
    )
    # Note: We no longer mock .close() as it's not called in the refactored task

    return mock_service_instance


# Removed mock_session_task3


@pytest.fixture
def mock_uow_task3(mocker):
    """Fixture to mock the SqlModelUnitOfWork for Task 3 tests."""
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.SqlModelUnitOfWork"
    )
    mock_uow_instance = MagicMock(spec=SqlModelUnitOfWork)
    mock_repo_instance = MagicMock(spec=DocumentRepository)
    mock_uow_instance.documents = mock_repo_instance
    mock_uow_class.return_value.__enter__.return_value = mock_uow_instance
    # Add mocks for commit/rollback if needed for specific failure tests
    # mock_uow_instance.commit = MagicMock()
    # mock_uow_instance.rollback = MagicMock()
    return mock_uow_class, mock_uow_instance, mock_repo_instance


@pytest.fixture
def pending_metadata_records() -> list[FileRecord]:
    """Creates a list of dummy FileRecord objects with PENDING_METADATA status."""
    # Creates two distinct records for testing different scenarios if needed
    return [
        FileRecord(
            id=uuid.uuid4(),
            source_path="/path/file1.pdf",
            status=FileStatus.PENDING_METADATA,
            extracted_text="Sample text for metadata extraction 1.",
            blob=b"pdf1",
            meta_data=None,
        ),
        FileRecord(
            id=uuid.uuid4(),
            source_path="/path/file2.txt",  # Different type for variety
            status=FileStatus.PENDING_METADATA,
            extracted_text="Sample text for metadata extraction 2.",
            blob=b"txt2",
            meta_data=None,
        ),
    ]


# Removed mock_file_repo_task3


# --- Test Functions ---


@pytest.mark.asyncio
async def test_run_task_3_success(
    mock_metadata_service: MagicMock,
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 happy path: finds records, extracts metadata, updates status using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records

    # Patch asyncio.sleep to avoid actual sleeping
    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()  # No engine arg

    assert found == 2
    assert success == 2
    assert errors == 0
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        FileStatus.PENDING_METADATA
    )
    assert mock_metadata_service.extract_metadata.call_count == 2

    # Check the status and metadata of the record objects passed to the repo mock
    record1 = pending_metadata_records[0]
    record2 = pending_metadata_records[1]
    assert record1.status == FileStatus.COMPLETED
    assert record1.meta_data is not None
    assert record1.meta_data["document_type"] == "Test Doc"
    assert record2.status == FileStatus.COMPLETED
    assert record2.meta_data is not None
    assert record2.meta_data["document_type"] == "Test Doc"

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_no_records_found(
    mock_metadata_service: MagicMock,
    mock_uow_task3,
):
    """Test Task 3 when no records with PENDING_METADATA status are found using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = []  # Simulate no records

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()  # No engine arg

    assert found == 0
    assert success == 0
    assert errors == 0
    mock_metadata_service.extract_metadata.assert_not_called()
    # Verify UoW usage (entered and exited even if no records)
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_no_extracted_text(
    mock_metadata_service: MagicMock,  # Service still needed for init check
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 when a record is found but has no extracted_text using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    # Modify one record to have no text
    pending_metadata_records[0].extracted_text = None
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()  # No engine arg

    assert found == 2
    assert success == 1  # Only the second record succeeds
    assert errors == 1  # First record causes an error
    # Ensure metadata extraction was only called for the second record
    mock_metadata_service.extract_metadata.assert_called_once_with(
        pending_metadata_records[
            1
        ].extracted_text  # Called only with text from record 2
    )

    # Check final status of records
    assert pending_metadata_records[0].status == FileStatus.FAILED_UNKNOWN
    assert pending_metadata_records[1].status == FileStatus.COMPLETED

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_metadata_extraction_returns_none(
    mock_metadata_service: MagicMock,
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 when metadata extraction call returns None using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records
    mock_metadata_service.extract_metadata.return_value = (
        None  # Simulate API returning None for both calls
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()  # No engine arg

    assert found == 2
    assert success == 0
    assert errors == 2  # Both records fail metadata extraction
    assert mock_metadata_service.extract_metadata.call_count == 2
    assert pending_metadata_records[0].status == FileStatus.FAILED_METADATA
    assert pending_metadata_records[1].status == FileStatus.FAILED_METADATA

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_metadata_extraction_exception(
    mock_metadata_service: MagicMock,
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 when metadata extraction call raises an exception using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records
    api_error = Exception("Simulated API Failure")
    mock_metadata_service.extract_metadata.side_effect = api_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()  # No engine arg

    assert found == 2
    assert success == 0
    assert errors == 2  # Both records fail due to API error
    assert mock_metadata_service.extract_metadata.call_count == 2
    assert pending_metadata_records[0].status == FileStatus.FAILED_METADATA
    assert pending_metadata_records[1].status == FileStatus.FAILED_METADATA

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_service_init_fails(mocker):
    """Test Task 3 when MetadataExtractionService fails to initialize."""
    init_error = RuntimeError("Service init failed")
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService",
        side_effect=init_error,
    )
    # Mock UoW to check it's NOT called
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.SqlModelUnitOfWork"
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()

    assert found == 0
    assert success == 0
    assert errors == 1  # The service init failure
    mock_uow_class.assert_not_called()  # UoW should not be entered


@pytest.mark.asyncio
async def test_run_task_3_uow_context_fails(mocker, mock_metadata_service):
    """Test Task 3 when the UoW context manager itself fails on entry."""
    uow_error = Exception("DB Connection Failed")
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.SqlModelUnitOfWork"
    )
    mock_uow_class.return_value.__enter__.side_effect = uow_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()

    assert found == 0  # Found count is determined inside UoW
    assert success == 0
    assert errors == 1  # The UoW entry failure
    mock_metadata_service.extract_metadata.assert_not_called()
    mock_uow_class.assert_called_once()  # UoW class was called
    mock_uow_class.return_value.__enter__.assert_called_once()  # __enter__ was attempted
    mock_uow_class.return_value.__exit__.assert_not_called()  # __exit__ not called


@pytest.mark.asyncio
async def test_run_task_3_uow_commit_fails(
    mocker, mock_metadata_service: MagicMock, mock_uow_task3, pending_metadata_records
):
    """Test Task 3 when the UoW commit fails after processing."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records

    # Simulate commit failure by making __exit__ raise an error
    commit_error = Exception("Simulated Commit Failure")
    mock_uow_class.return_value.__exit__.side_effect = commit_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3()

    # Counts reflect successful processing *before* commit failure
    assert found == 2
    assert success == 2
    # The error count should include the final UoW commit error
    assert errors == 1

    # Check record state *before* commit failed
    assert pending_metadata_records[0].status == FileStatus.COMPLETED
    assert pending_metadata_records[1].status == FileStatus.COMPLETED

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


# Remove obsolete tests:
# - test_run_task_3_success_commit_fails (replaced by test_run_task_3_uow_commit_fails)
# - test_run_task_3_api_error_commit_fails (UoW commit failure is tested separately)
# - test_run_task_3_service_close_fails (service.close not called anymore)
# - test_run_task_3_no_text_get_fails (nested session.get logic removed)
