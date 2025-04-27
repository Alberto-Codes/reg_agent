# tests/pipelines/ingestion/tasks/test_task_3_metadata.py

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# from sqlalchemy.engine import Engine # Removed
# from sqlmodel import Session # Removed
from reg_agent.core.db.models import FileRecord, FileStatus

# Keep this for type hinting the mock repository
from reg_agent.core.db.repositories import DocumentRepository

# Import UoW for type hinting the mock
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import (
    MetadataExtractionService,
    Task3Result,
    run_task_3,
)
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
            filename="file1.pdf",
            status=FileStatus.PENDING_METADATA,
            extracted_text="Sample text for metadata extraction 1.",
            blob=b"pdf1",
            meta_data=None,
        ),
        FileRecord(
            id=uuid.uuid4(),
            source_path="/path/file2.txt",  # Different type for variety
            filename="file2.txt",
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
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 2
    assert result["success"] == 2
    assert result["errors"] == 0
    assert not result["error_details"]
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        [
            FileStatus.PENDING_METADATA,
            FileStatus.FAILED_METADATA,
            FileStatus.FAILED_LLM_OUTPUT,
        ]
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
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 0
    assert result["success"] == 0
    assert result["errors"] == 0
    assert not result["error_details"]
    mock_metadata_service.extract_metadata.assert_not_called()
    # Verify UoW usage (entered and exited even if no records)
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()

    # Check that the repo method was still called with the correct statuses
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        [
            FileStatus.PENDING_METADATA,
            FileStatus.FAILED_METADATA,
            FileStatus.FAILED_LLM_OUTPUT,
        ]
    )


@pytest.mark.asyncio
async def test_run_task_3_no_extracted_text(
    mock_metadata_service: MagicMock,  # Service still needed for init check
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 when a record is found but has no extracted_text using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    # Modify one record to have no text
    record_with_no_text = pending_metadata_records[0]
    record_with_text = pending_metadata_records[1]
    record_with_no_text.extracted_text = None
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 2
    assert result["success"] == 1  # Only the second record succeeds
    assert result["errors"] == 1  # First record causes an error
    assert len(result["error_details"]) == 1
    assert result["error_details"][0]["record_id"] == str(record_with_no_text.id)
    assert result["error_details"][0]["filename"] == record_with_no_text.filename
    assert result["error_details"][0]["status"] == FileStatus.FAILED_UNKNOWN
    assert "no extracted text" in result["error_details"][0]["error_message"]

    # Ensure metadata extraction was only called for the second record
    mock_metadata_service.extract_metadata.assert_called_once_with(
        record_with_text.extracted_text  # Called only with text from record 2
    )

    # Check that the repo method was called with the correct statuses
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        [
            FileStatus.PENDING_METADATA,
            FileStatus.FAILED_METADATA,
            FileStatus.FAILED_LLM_OUTPUT,
        ]
    )

    # Check final status of records
    assert record_with_no_text.status == FileStatus.FAILED_UNKNOWN
    assert record_with_text.status == FileStatus.COMPLETED

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
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 2
    assert result["success"] == 0
    assert result["errors"] == 2  # Both records fail metadata extraction
    assert len(result["error_details"]) == 2
    assert result["error_details"][0]["status"] == FileStatus.FAILED_LLM_OUTPUT
    assert result["error_details"][1]["status"] == FileStatus.FAILED_LLM_OUTPUT
    assert (
        "LLM output invalid/unparsable" in result["error_details"][0]["error_message"]
    )

    assert mock_metadata_service.extract_metadata.call_count == 2
    # Check final status is FAILED_LLM_OUTPUT
    assert pending_metadata_records[0].status == FileStatus.FAILED_LLM_OUTPUT
    assert pending_metadata_records[1].status == FileStatus.FAILED_LLM_OUTPUT

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()

    # Check that the repo method was called with the correct statuses
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        [
            FileStatus.PENDING_METADATA,
            FileStatus.FAILED_METADATA,
            FileStatus.FAILED_LLM_OUTPUT,
        ]
    )


@pytest.mark.asyncio
async def test_run_task_3_metadata_extraction_exception(
    mock_metadata_service: MagicMock,
    mock_uow_task3,
    pending_metadata_records,
):
    """Test Task 3 when metadata extraction call raises an exception using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records
    api_error_message = "Simulated API Failure"
    api_error = Exception(api_error_message)
    mock_metadata_service.extract_metadata.side_effect = api_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 2
    assert result["success"] == 0
    assert result["errors"] == 2  # Both records fail due to API error
    assert len(result["error_details"]) == 2
    assert result["error_details"][0]["status"] == FileStatus.FAILED_METADATA
    assert result["error_details"][1]["status"] == FileStatus.FAILED_METADATA
    assert api_error_message in result["error_details"][0]["error_message"]
    assert api_error_message in result["error_details"][1]["error_message"]

    # Check that the service was called for both records (with retries)
    # MAX_RETRIES = 3, so 3 calls per record = 6 total calls
    assert mock_metadata_service.extract_metadata.call_count == 2 * 3

    # Check final status is FAILED_METADATA
    assert pending_metadata_records[0].status == FileStatus.FAILED_METADATA
    assert pending_metadata_records[1].status == FileStatus.FAILED_METADATA

    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_run_task_3_service_init_fails(mocker):
    """Test Task 3 when MetadataExtractionService fails to initialize."""
    init_error_message = "Service init failed"
    init_error = RuntimeError(init_error_message)
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService",
        side_effect=init_error,
    )
    # Mock UoW to check it's NOT called
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.SqlModelUnitOfWork"
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 0
    assert result["success"] == 0
    assert result["errors"] == 1  # Single error for service init failure
    assert len(result["error_details"]) == 1
    assert (
        result["error_details"][0]["record_id"] == "N/A"
    )  # Indicate service level error
    assert result["error_details"][0]["status"] == FileStatus.FAILED_METADATA
    assert init_error_message in result["error_details"][0]["error_message"]

    # UoW should not have been entered
    mock_uow_class.assert_not_called()


@pytest.mark.asyncio
async def test_run_task_3_uow_context_fails(mocker, mock_metadata_service):
    """Test Task 3 when the UoW context manager itself fails on entry."""
    uow_error_message = "DB Connection Failed"
    uow_error = Exception(uow_error_message)
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_3_metadata.SqlModelUnitOfWork"
    )
    mock_uow_class.return_value.__enter__.side_effect = uow_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 0  # Found count is from *inside* UoW
    assert result["success"] == 0
    assert result["errors"] == 1  # UoW context error counts as one
    assert len(result["error_details"]) == 1
    assert result["error_details"][0]["status"] == FileStatus.FAILED_UNKNOWN
    assert uow_error_message in result["error_details"][0]["error_message"]

    mock_metadata_service.extract_metadata.assert_not_called()
    # UoW class was called, but __enter__ failed
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_not_called()  # Should not be called if __enter__ fails


@pytest.mark.asyncio
async def test_run_task_3_uow_commit_fails(
    mocker, mock_metadata_service: MagicMock, mock_uow_task3, pending_metadata_records
):
    """Test Task 3 when the UoW commit fails after processing."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task3
    mock_repo_instance.get_records_by_status.return_value = pending_metadata_records

    # Simulate commit failure by making __exit__ raise an error
    commit_error_message = "Simulated Commit Failure"
    commit_error = Exception(commit_error_message)
    mock_uow_class.return_value.__exit__.side_effect = commit_error

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result: Task3Result = await run_task_3()  # Capture the result dictionary

    assert result["found"] == 2  # Found count happens inside UoW before exit fails
    assert result["success"] == 2  # Success count happens inside UoW
    assert result["errors"] == 1  # UoW commit error counts as one
    assert len(result["error_details"]) == 1
    assert result["error_details"][0]["status"] == FileStatus.FAILED_UNKNOWN
    assert commit_error_message in result["error_details"][0]["error_message"]

    # Service was called
    assert mock_metadata_service.extract_metadata.call_count == 2
    # UoW context was entered and exit was attempted
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()
