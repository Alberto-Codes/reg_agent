# tests/pipelines/ingestion/tasks/test_task_2_ocr.py

import uuid
from unittest.mock import MagicMock

import pytest

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork
from reg_agent.pipelines.ingestion.tasks.task_2_ocr import run_task_2
from reg_agent.services.ocr_service import OcrService

# Use the existing engine fixture from connection tests
# from tests.core.db.test_connection import test_engine # noqa: F401

# --- Fixtures ---


@pytest.fixture
def mock_ocr_service(mocker) -> MagicMock:
    """Mocks the OcrService."""
    mock_service = mocker.MagicMock(spec=OcrService)
    mock_service.converter = True  # Simulate initialized converter
    mock_service.extract_markdown_from_file.return_value = "# Mock OCR Text"
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService",
        return_value=mock_service,
    )
    return mock_service


@pytest.fixture
def mock_uow_task2(mocker):
    """Fixture to mock the SqlModelUnitOfWork for Task 2 tests."""
    # Mock the UoW class within the task module
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.SqlModelUnitOfWork"
    )
    mock_uow_instance = MagicMock(spec=SqlModelUnitOfWork)
    mock_repo_instance = MagicMock(spec=DocumentRepository)
    mock_uow_instance.documents = mock_repo_instance
    mock_uow_class.return_value.__enter__.return_value = mock_uow_instance
    return mock_uow_class, mock_uow_instance, mock_repo_instance


@pytest.fixture
def pending_ocr_records() -> list[FileRecord]:
    """Creates a list of dummy FileRecord objects with PENDING_PROCESS status."""
    # Return fresh copies each time to avoid state leakage between tests
    return [
        FileRecord(
            id=uuid.uuid4(),
            source_path="/path/file1.pdf",
            status=FileStatus.PENDING_PROCESS,
            blob=b"pdf_content_1",  # Add dummy blob
            extracted_text=None,
        ),
        FileRecord(
            id=uuid.uuid4(),
            source_path="/path/file2.pdf",
            status=FileStatus.PENDING_PROCESS,
            blob=b"pdf_content_2",  # Add dummy blob
            extracted_text=None,
        ),
    ]


# --- Test Functions ---


def test_run_task_2_success(
    mock_ocr_service: MagicMock,
    mock_uow_task2,
    pending_ocr_records,
):
    """Test Task 2 happy path: finds records, performs OCR, updates status using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task2
    # Configure the mock repo provided by the UoW mock
    mock_repo_instance.get_records_by_status.return_value = pending_ocr_records

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 2
    assert success == 2
    assert skipped == 0
    assert errors == 0
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        FileStatus.PENDING_PROCESS
    )
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    # Check if status was updated correctly on the mock records
    assert pending_ocr_records[0].status == FileStatus.PENDING_METADATA
    assert pending_ocr_records[1].status == FileStatus.PENDING_METADATA
    assert pending_ocr_records[0].extracted_text == "# Mock OCR Text"
    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_2_no_records_found(
    mock_ocr_service: MagicMock,
    mock_uow_task2,
):
    """Test Task 2 when no records with PENDING_PROCESS status are found using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task2
    mock_repo_instance.get_records_by_status.return_value = []  # Simulate no records

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 0
    mock_repo_instance.get_records_by_status.assert_called_once_with(
        FileStatus.PENDING_PROCESS
    )
    mock_ocr_service.extract_markdown_from_file.assert_not_called()
    # Verify UoW usage (entered and exited even if no records)
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_2_ocr_skipped(
    mock_ocr_service: MagicMock,
    mock_uow_task2,
    pending_ocr_records,
):
    """Test Task 2 when OCR service returns None (e.g., non-PDF) using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task2
    mock_repo_instance.get_records_by_status.return_value = pending_ocr_records
    mock_ocr_service.extract_markdown_from_file.return_value = None  # Simulate skip

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 2
    assert success == 0
    assert skipped == 2
    assert errors == 0
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    assert pending_ocr_records[0].status == FileStatus.SKIPPED_OCR
    assert pending_ocr_records[1].status == FileStatus.SKIPPED_OCR
    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_2_ocr_error(
    mock_ocr_service: MagicMock,
    mock_uow_task2,
    pending_ocr_records,
):
    """Test Task 2 when OCR service raises an exception using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow_task2
    mock_repo_instance.get_records_by_status.return_value = pending_ocr_records
    ocr_exception = Exception("Simulated OCR engine failure")
    mock_ocr_service.extract_markdown_from_file.side_effect = ocr_exception

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 2
    assert success == 0
    assert skipped == 0
    assert errors == 2
    assert mock_ocr_service.extract_markdown_from_file.call_count == 2
    assert pending_ocr_records[0].status == FileStatus.FAILED_OCR
    assert pending_ocr_records[1].status == FileStatus.FAILED_OCR
    # Verify UoW usage
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_2_ocr_service_init_fails(mocker):
    """Test Task 2 when OcrService fails to initialize (UoW should not be used)."""
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService",
        side_effect=RuntimeError("Init failed"),
    )
    # Mock UoW to check it's NOT called
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.SqlModelUnitOfWork"
    )

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 1  # Error count should reflect the init failure
    mock_uow_class.assert_not_called()  # UoW should not be entered if service fails


def test_run_task_2_ocr_service_converter_none(mocker):
    """Test Task 2 when OcrService initializes but converter is None (UoW not used)."""
    mock_service = mocker.MagicMock(spec=OcrService)
    mock_service.converter = None  # Simulate uninitialized converter
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.OcrService",
        return_value=mock_service,
    )
    # Mock UoW to check it's NOT called
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_2_ocr.SqlModelUnitOfWork"
    )

    found, success, skipped, errors = run_task_2()  # No engine arg

    assert found == 0
    assert success == 0
    assert skipped == 0
    assert errors == 0  # Task skips gracefully, no error
    mock_uow_class.assert_not_called()  # UoW should not be entered


# --- End of Test Functions ---
