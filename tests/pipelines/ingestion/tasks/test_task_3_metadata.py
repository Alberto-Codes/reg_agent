# tests/pipelines/ingestion/tasks/test_task_3_metadata.py

import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

from sqlalchemy.engine import Engine
from sqlmodel import Session

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import run_task_3
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.schemas.metadata import RegulationDocumentMetadata

# Use the existing engine fixture from connection tests
from tests.core.db.test_connection import test_engine # noqa: F401

# --- Fixtures ---

@pytest.fixture
def mock_metadata_service(mocker) -> MagicMock:
    """Mocks the MetadataExtractionService and its async methods."""
    # Mock the service instance returned by the constructor
    mock_service_instance = mocker.MagicMock(spec=MetadataExtractionService)

    # Mock the async extract_metadata method
    # Create a dummy metadata model instance to return
    dummy_metadata = RegulationDocumentMetadata(
        document_type="Test Doc",
        issuing_agency="Test Agency",
        subject_institution="Test Bank",
        document_identifier="Test-123",
        summary="Test summary.",
        key_topics=["Topic A"], # Optional field
        action_items=[]          # Optional field
    )
    mock_service_instance.extract_metadata = AsyncMock(return_value=dummy_metadata)

    # Mock the async close method
    mock_service_instance.close = AsyncMock()

    # Patch the constructor to return our mocked instance
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService", return_value=mock_service_instance)

    return mock_service_instance # Return the instance for assertion checks if needed

@pytest.fixture
def mock_session_task3(mocker):
    """Fixture to mock the get_session context manager and the session object for Task 3 tests."""
    mock_sess = mocker.MagicMock(spec=Session)
    # Mock session.get to return a dummy record when called
    # This requires knowing the ID used in the test
    mock_record = FileRecord(id=uuid.uuid4(), source_path="/path/file1.pdf", status=FileStatus.PENDING_METADATA, extracted_text="Some text")
    mock_sess.get.return_value = mock_record

    mock_context = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.get_session")
    mock_context.return_value.__enter__.return_value = mock_sess
    # Store mock_record on the session mock for tests to access the expected ID
    mock_sess._mock_record = mock_record
    return mock_sess

@pytest.fixture
def pending_metadata_records(mock_session_task3) -> list[FileRecord]:
    """Creates a list containing the dummy FileRecord from the session mock."""
    # Use the same record ID that session.get will return
    record = mock_session_task3._mock_record
    record.status = FileStatus.PENDING_METADATA # Ensure correct initial status
    record.extracted_text = "Sample text for metadata extraction."
    return [record]

@pytest.fixture
def mock_file_repo_task3(mocker, pending_metadata_records) -> MagicMock:
    """Mocks the FileRepository specifically for Task 3 tests."""
    mock_repo = mocker.MagicMock(spec=FileRepository)
    # Simulate finding the records in the initial fetch
    mock_repo.get_records_by_status.return_value = pending_metadata_records
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.FileRepository", return_value=mock_repo)
    return mock_repo

# --- Test Functions ---
# Note: Tests need to be async due to run_task_3 being async

@pytest.mark.asyncio
async def test_run_task_3_success(test_engine: Engine, mock_metadata_service: MagicMock, mock_session_task3: MagicMock, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 happy path: finds records, extracts metadata, updates status."""
    # Patch asyncio.sleep to avoid actual sleeping
    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 1
    assert errors == 0
    mock_file_repo_task3.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_metadata_service.extract_metadata.assert_called_once()
    mock_metadata_service.close.assert_called_once() # Ensure service is closed

    # Check that session.get was called to retrieve the record for update
    update_session = mock_session_task3 # Session mock used for updates
    record_id_to_find = pending_metadata_records[0].id
    update_session.get.assert_called_with(FileRecord, record_id_to_find)

    # Check that session.add was called to stage the update
    update_session.add.assert_called_once()
    # Check the status and metadata of the record mock that was supposedly added
    added_record_arg = update_session.add.call_args[0][0]
    assert added_record_arg.status == FileStatus.COMPLETED
    assert added_record_arg.meta_data is not None
    assert added_record_arg.meta_data["document_type"] == "Test Doc"

@pytest.mark.asyncio
async def test_run_task_3_no_records_found(test_engine: Engine, mock_metadata_service: MagicMock, mock_file_repo_task3: MagicMock):
    """Test Task 3 when no records with PENDING_METADATA status are found."""
    mock_file_repo_task3.get_records_by_status.return_value = [] # Simulate no records

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 0
    assert success == 0
    assert errors == 0
    mock_metadata_service.extract_metadata.assert_not_called()
    mock_metadata_service.close.assert_not_called()

@pytest.mark.asyncio
async def test_run_task_3_no_extracted_text(test_engine: Engine, mock_session_task3: MagicMock, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 when a record is found but has no extracted_text."""
    pending_metadata_records[0].extracted_text = None # Simulate missing text

    with patch("asyncio.sleep", new_callable=AsyncMock):
         found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0
    assert errors == 1 # Should count as error
    # Ensure update to FAILED_UNKNOWN happened
    update_session = mock_session_task3
    record_id_to_find = pending_metadata_records[0].id
    update_session.get.assert_called_with(FileRecord, record_id_to_find)
    update_session.add.assert_called_once()
    added_record_arg = update_session.add.call_args[0][0]
    assert added_record_arg.status == FileStatus.FAILED_UNKNOWN

@pytest.mark.asyncio
async def test_run_task_3_metadata_extraction_returns_none(test_engine: Engine, mock_metadata_service: MagicMock, mock_session_task3: MagicMock, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 when metadata extraction call returns None."""
    mock_metadata_service.extract_metadata.return_value = None # Simulate API returning None

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0
    assert errors == 1
    mock_metadata_service.extract_metadata.assert_called_once()
    mock_metadata_service.close.assert_called_once()
    # Check status updated to FAILED_METADATA
    update_session = mock_session_task3
    added_record_arg = update_session.add.call_args[0][0]
    assert added_record_arg.status == FileStatus.FAILED_METADATA

@pytest.mark.asyncio
async def test_run_task_3_metadata_extraction_exception(test_engine: Engine, mock_metadata_service: MagicMock, mock_session_task3: MagicMock, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 when metadata extraction call raises an exception."""
    extraction_exception = ValueError("Simulated API error")
    mock_metadata_service.extract_metadata.side_effect = extraction_exception

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0
    assert errors == 1
    mock_metadata_service.extract_metadata.assert_called_once()
    # Close should still be called in finally block
    mock_metadata_service.close.assert_called_once()
    # Check status updated to FAILED_METADATA
    update_session = mock_session_task3

    # --- Check DB interaction within the exception handler --- #
    # get is called once inside the 'except' block's session
    assert update_session.get.call_count == 1
    record_id_to_find = pending_metadata_records[0].id
    update_session.get.assert_called_with(FileRecord, record_id_to_find)

    # add is called once inside the 'except' block's session (since get found the record)
    assert update_session.add.call_count == 1
    failed_record_arg = update_session.add.call_args[0][0] # Get arg from the single call
    assert failed_record_arg.status == FileStatus.FAILED_METADATA 