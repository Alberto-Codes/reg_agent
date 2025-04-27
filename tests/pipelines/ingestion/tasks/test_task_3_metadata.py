# tests/pipelines/ingestion/tasks/test_task_3_metadata.py

import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

from sqlalchemy.engine import Engine
from sqlmodel import Session

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import run_task_3, MetadataExtractionService
from reg_agent.schemas.metadata import RegulationDocumentMetadata, ExtractedMetadata

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

@pytest.mark.asyncio
async def test_run_task_3_initial_fetch_fails(test_engine: Engine, mocker):
    """Test Task 3 when the initial DB query for records fails."""
    # Mock the FileRepository constructor to return a repo that fails
    mock_repo = mocker.MagicMock(spec=FileRepository)
    mock_repo.get_records_by_status.side_effect = Exception("Initial DB connection error")
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.FileRepository").return_value = mock_repo
    # Mock get_session just to avoid issues, though it shouldn't be heavily used if repo fails
    mock_session_ctx = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.get_session")

    # Mock the service constructor so it doesn't get called
    mock_service_constructor = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService")

    found, success, errors = await run_task_3(test_engine)

    assert found == 0
    assert success == 0
    assert errors == 0
    mock_repo.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_service_constructor.assert_not_called()

@pytest.mark.asyncio
async def test_run_task_3_success_commit_fails(test_engine: Engine, mocker, mock_metadata_service: MagicMock, pending_metadata_records):
    """Test Task 3 success case but DB commit fails during update."""
    record_id_to_process = pending_metadata_records[0].id

    # Mock FileRepository for initial fetch
    mock_repo = mocker.MagicMock(spec=FileRepository)
    mock_repo.get_records_by_status.return_value = pending_metadata_records
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.FileRepository").return_value = mock_repo

    # Mock sessions returned by get_session
    mock_initial_session = MagicMock(spec=Session)
    mock_update_session_success = MagicMock(spec=Session)
    mock_update_session_fail_commit = MagicMock(spec=Session)

    # Configure the session that fails on commit
    mock_update_session_fail_commit.get.return_value = pending_metadata_records[0] # Allow get to succeed
    # mock_update_session_fail_commit.add.side_effect = commit_exception # Remove side effect on add

    # Control which session is returned by get_session
    session_call_count = 0
    commit_exception = Exception("Simulated DB Commit Error")
    def get_session_side_effect(*args, **kwargs):
        nonlocal session_call_count
        session_call_count += 1
        mock_ctx = MagicMock()
        if session_call_count == 1:
            # First call is initial fetch
            mock_ctx.__enter__.return_value = mock_initial_session
            mock_ctx.__exit__.return_value = None # Success
            return mock_ctx
        elif session_call_count == 2:
            # Second call is the update attempt after successful API call
            mock_ctx.__enter__.return_value = mock_update_session_fail_commit
            # Fail on exit (commit)
            mock_ctx.__exit__.side_effect = commit_exception
            return mock_ctx
        else:
            raise RuntimeError("Unexpected call to get_session")

    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.get_session", side_effect=get_session_side_effect)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0 # Success incremented then decremented
    assert errors == 1  # Error count incremented due to commit failure

    mock_repo.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_metadata_service.extract_metadata.assert_called_once()
    mock_metadata_service.close.assert_called_once()

    # Verify the failing session interaction
    mock_update_session_fail_commit.get.assert_called_once_with(FileRecord, record_id_to_process)
    mock_update_session_fail_commit.add.assert_called_once() # Add was attempted

@pytest.mark.asyncio
async def test_run_task_3_api_error_commit_fails(test_engine: Engine, mocker, mock_metadata_service: MagicMock, pending_metadata_records):
    """Test Task 3 API error case where subsequent DB commit fails."""
    record_id_to_process = pending_metadata_records[0].id

    # Mock FileRepository for initial fetch
    mock_repo = mocker.MagicMock(spec=FileRepository)
    mock_repo.get_records_by_status.return_value = pending_metadata_records
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.FileRepository").return_value = mock_repo

    # Mock the service to raise an error during extraction
    extraction_exception = ValueError("Simulated API error")
    mock_metadata_service.extract_metadata.side_effect = extraction_exception

    # Mock sessions returned by get_session
    mock_initial_session = MagicMock(spec=Session)
    mock_update_session_fail_commit = MagicMock(spec=Session)

    # Configure the session that fails on commit
    mock_update_session_fail_commit.get.return_value = pending_metadata_records[0] # Allow get to succeed
    # commit_exception = Exception("Simulated DB Commit Error After API Fail") # Defined below
    # mock_update_session_fail_commit.add.side_effect = commit_exception # Remove side effect on add

    # Control which session is returned by get_session
    session_call_count = 0
    commit_exception = Exception("Simulated DB Commit Error After API Fail")
    def get_session_side_effect(*args, **kwargs):
        nonlocal session_call_count
        session_call_count += 1
        mock_ctx = MagicMock()
        if session_call_count == 1: # Initial fetch
            mock_ctx.__enter__.return_value = mock_initial_session
            mock_ctx.__exit__.return_value = None # Success
            return mock_ctx
        elif session_call_count == 2: # Update attempt within API error handler
            mock_ctx.__enter__.return_value = mock_update_session_fail_commit
            # Fail on exit (commit)
            mock_ctx.__exit__.side_effect = commit_exception
            return mock_ctx
        else:
            raise RuntimeError("Unexpected call to get_session")

    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.get_session", side_effect=get_session_side_effect)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0
    assert errors == 1 # Should only count as one error overall

    mock_repo.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_metadata_service.extract_metadata.assert_called_once()
    mock_metadata_service.close.assert_called_once()

    # Verify the failing session interaction within the exception handler
    mock_update_session_fail_commit.get.assert_called_once_with(FileRecord, record_id_to_process)
    mock_update_session_fail_commit.add.assert_called_once() # Add was attempted

@pytest.mark.asyncio
async def test_run_task_3_service_close_fails(test_engine: Engine, mock_metadata_service: MagicMock, mock_session_task3: MagicMock, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 when the metadata_service.close() call fails."""
    # Simulate close failing
    close_exception = RuntimeError("Failed to close service cleanly")
    mock_metadata_service.close.side_effect = close_exception

    # Patch asyncio.sleep to avoid actual sleeping
    with patch("asyncio.sleep", new_callable=AsyncMock):
        found, success, errors = await run_task_3(test_engine)

    # Failure during close should not affect the outcome counts
    assert found == 1
    assert success == 1 # Metadata was extracted successfully before close failed
    assert errors == 0 # Error in finally block doesn't increment error count

    mock_file_repo_task3.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_metadata_service.extract_metadata.assert_called_once()
    mock_metadata_service.close.assert_called_once() # Close was attempted

    # Check that DB update still happened correctly
    update_session = mock_session_task3
    record_id_to_find = pending_metadata_records[0].id
    update_session.get.assert_called_with(FileRecord, record_id_to_find)
    update_session.add.assert_called_once()
    added_record_arg = update_session.add.call_args[0][0]
    assert added_record_arg.status == FileStatus.COMPLETED
    assert added_record_arg.meta_data is not None
    assert added_record_arg.meta_data["document_type"] == "Test Doc"

@pytest.mark.asyncio
async def test_run_task_3_no_text_get_fails(test_engine: Engine, mocker, mock_file_repo_task3: MagicMock, pending_metadata_records):
    """Test Task 3 no text case where the DB get fails during update."""
    record_to_process = pending_metadata_records[0]
    record_to_process.extracted_text = None # Simulate missing text
    record_id_to_process = record_to_process.id

    # Mock FileRepository for initial fetch
    # Need to use the same repo mock setup as the test below
    mock_repo = mocker.MagicMock(spec=FileRepository)
    mock_repo.get_records_by_status.return_value = pending_metadata_records
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.FileRepository").return_value = mock_repo

    # Mock sessions returned by get_session
    mock_initial_session = MagicMock(spec=Session)
    mock_update_session_get_none = MagicMock(spec=Session)
    mock_update_session_get_none.get.return_value = None # Simulate record not found during update

    # Control which session is returned by get_session
    session_call_count = 0
    def get_session_side_effect(*args, **kwargs):
        nonlocal session_call_count
        session_call_count += 1
        if session_call_count == 1: # Initial fetch
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_initial_session
            mock_ctx.__exit__.return_value = None
            return mock_ctx
        elif session_call_count == 2: # Update attempt within no-text handler
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_update_session_get_none
            mock_ctx.__exit__.return_value = None
            return mock_ctx
        else:
            raise RuntimeError("Unexpected call to get_session")

    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.get_session", side_effect=get_session_side_effect)

    # Mock the service constructor so it doesn't get called
    mock_service_constructor = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.MetadataExtractionService")

    with patch("asyncio.sleep", new_callable=AsyncMock):
         found, success, errors = await run_task_3(test_engine)

    assert found == 1
    assert success == 0
    assert errors == 1 # Error because record couldn't be updated

    mock_repo.get_records_by_status.assert_called_once_with(FileStatus.PENDING_METADATA)
    mock_service_constructor.assert_not_called()

    # Verify the failing session interaction within the no-text handler
    mock_update_session_get_none.get.assert_called_once_with(FileRecord, record_id_to_process)
    mock_update_session_get_none.add.assert_not_called() # Add should not be called if get fails 