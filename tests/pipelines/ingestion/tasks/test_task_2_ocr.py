# tests/pipelines/ingestion/tasks/test_task_2_ocr.py

import pytest
from pathlib import Path
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import Engine
from sqlmodel import Session

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.pipelines.ingestion.tasks.task_2_ocr import run_task_2
from reg_agent.services.ocr_service import OcrService

# Use the existing engine fixture from connection tests
# from tests.core.db.test_connection import test_engine # noqa: F401

# --- Fixtures ---

@pytest.fixture
def mock_ocr_service(mocker) -> MagicMock:
    """Mocks the OcrService."""
    mock_service = mocker.MagicMock(spec=OcrService)
    mock_service.converter = True # Simulate initialized converter
    mock_service.extract_markdown_from_file.return_value = "# Mock OCR Text"
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService", return_value=mock_service)
    return mock_service

@pytest.fixture
def mock_session_task2(mocker):
    """Fixture to mock the get_session context manager and the session object for Task 2 tests."""
    mock_sess = mocker.MagicMock(spec=Session)
    mock_context = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.get_session")
    mock_context.return_value.__enter__.return_value = mock_sess
    return mock_sess

@pytest.fixture
def pending_ocr_records() -> list[FileRecord]:
    """Creates a list of dummy FileRecord objects with PENDING_PROCESS status."""
    return [
        FileRecord(id=uuid.uuid4(), source_path="/path/file1.pdf", status=FileStatus.PENDING_PROCESS),
        FileRecord(id=uuid.uuid4(), source_path="/path/file2.pdf", status=FileStatus.PENDING_PROCESS),
    ]

@pytest.fixture
def mock_file_repo_task2(mocker, pending_ocr_records) -> MagicMock:
    """Mocks the FileRepository specifically for Task 2 tests."""
    mock_repo = mocker.MagicMock(spec=FileRepository)
    mock_repo.get_records_by_status.return_value = pending_ocr_records
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.FileRepository", return_value=mock_repo)
    return mock_repo

# --- Test Functions ---

def test_run_task_2_success(test_engine: Engine, mock_ocr_service: MagicMock, mock_session_task2: MagicMock, mock_file_repo_task2: MagicMock, pending_ocr_records):
    """Test Task 2 happy path: finds records, performs OCR, updates status."""
    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 2
    assert success == 2
    assert skipped == 0
    assert errors == 0
    mock_file_repo_task2.get_records_by_status.assert_called_once_with(FileStatus.PENDING_PROCESS)
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    assert mock_session_task2.add.call_count == 2
    # Check if status was updated correctly on the mock records
    assert pending_ocr_records[0].status == FileStatus.PENDING_METADATA
    assert pending_ocr_records[1].status == FileStatus.PENDING_METADATA
    assert pending_ocr_records[0].extracted_text == "# Mock OCR Text"

def test_run_task_2_no_records_found(test_engine: Engine, mock_ocr_service: MagicMock, mock_session_task2: MagicMock, mock_file_repo_task2: MagicMock):
    """Test Task 2 when no records with PENDING_PROCESS status are found."""
    mock_file_repo_task2.get_records_by_status.return_value = [] # Simulate no records found

    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 0
    mock_file_repo_task2.get_records_by_status.assert_called_once_with(FileStatus.PENDING_PROCESS)
    mock_ocr_service.extract_markdown_from_file.assert_not_called()
    mock_session_task2.add.assert_not_called()

def test_run_task_2_ocr_skipped(test_engine: Engine, mock_ocr_service: MagicMock, mock_session_task2: MagicMock, mock_file_repo_task2: MagicMock, pending_ocr_records):
    """Test Task 2 when OCR service returns None (e.g., non-PDF)."""
    mock_ocr_service.extract_markdown_from_file.return_value = None # Simulate skip

    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 2
    assert success == 0
    assert skipped == 2
    assert errors == 0
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    assert mock_session_task2.add.call_count == 2
    assert pending_ocr_records[0].status == FileStatus.SKIPPED_OCR
    assert pending_ocr_records[1].status == FileStatus.SKIPPED_OCR

def test_run_task_2_ocr_error(test_engine: Engine, mock_ocr_service: MagicMock, mock_session_task2: MagicMock, mock_file_repo_task2: MagicMock, pending_ocr_records):
    """Test Task 2 when OCR service raises an exception."""
    ocr_exception = Exception("Simulated OCR engine failure")
    mock_ocr_service.extract_markdown_from_file.side_effect = ocr_exception

    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 2
    assert success == 0
    assert skipped == 0
    assert errors == 2
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    assert mock_session_task2.add.call_count == 2 # Add is called to update status to FAILED
    assert pending_ocr_records[0].status == FileStatus.FAILED_OCR
    assert pending_ocr_records[1].status == FileStatus.FAILED_OCR

def test_run_task_2_ocr_service_init_fails(test_engine: Engine, mocker):
    """Test Task 2 when OcrService fails to initialize."""
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService", side_effect=RuntimeError("Init failed"))
    mock_get_session = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.get_session")

    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 1 # Error count should reflect the init failure
    mock_get_session.assert_not_called() # Should not attempt DB ops if service fails

def test_run_task_2_ocr_service_converter_none(test_engine: Engine, mocker):
    """Test Task 2 when OcrService initializes but converter is None."""
    mock_service = mocker.MagicMock(spec=OcrService)
    mock_service.converter = None # Simulate uninitialized converter
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService", return_value=mock_service)
    mock_get_session = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.get_session")

    found, success, skipped, errors = run_task_2(test_engine)

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 0 # This case logs a warning and exits gracefully, not an error
    mock_get_session.assert_not_called()

# --- End of Test Functions --- 