"""Unit tests for the ingestion loader pipeline."""

import datetime
from pathlib import Path
from unittest.mock import (
    MagicMock,
    call,
)  # Import ANY for flexible argument matching

import pytest  # Use pytest fixtures and mocker

# Removed DuckDB import
# Removed direct connect_db import
from reg_agent.core.db.models import FileRecord  # Needed for creating expected objects
from reg_agent.pipelines.ingestion.loader import ingest_files

# Mock modules/classes used by the loader
# We will patch these within the test functions using mocker


@pytest.fixture
def mock_ocr_service(mocker) -> MagicMock:
    """Provides a mocked OcrService instance."""
    mock = mocker.MagicMock(name="MockOcrServiceInstance")
    mock.converter = True  # Simulate successful initialization by default
    mock.extract_markdown_from_file.return_value = "Extracted Markdown Text"
    # Patch the class within the loader module's scope
    mocker.patch("reg_agent.pipelines.ingestion.loader.OcrService", return_value=mock)
    return mock


@pytest.fixture
def mock_file_repository(mocker) -> MagicMock:
    """Provides a mocked FileRepository instance."""
    mock = mocker.MagicMock(name="MockFileRepositoryInstance")
    mock.exists_by_source_path.return_value = (
        False  # Assume file doesn't exist by default
    )
    # We don't mock add directly, as we want to check calls to it
    # Patch the class within the loader module's scope
    # Need to ensure this patch happens *before* get_session is called in the test,
    # as the repository is instantiated inside the session context.
    # It might be better to patch inside the test function after patching get_session.
    return mock  # Return the mock instance itself


@pytest.fixture
def mock_session_context(mocker, mock_file_repository) -> MagicMock:
    """Provides a mocked session context manager (get_session)."""
    mock_session = MagicMock(name="MockSession")
    # Patch the FileRepository class *before* get_session returns the context
    mocker.patch(
        "reg_agent.pipelines.ingestion.loader.FileRepository",
        return_value=mock_file_repository,
    )

    # Mock the context manager
    mock_context = MagicMock(name="MockSessionContext")
    mock_context.__enter__.return_value = mock_session  # yield mock_session
    mock_context.__exit__.return_value = None  # Simulate exiting without error

    # Patch get_session in the loader module
    mocker.patch(
        "reg_agent.pipelines.ingestion.loader.get_session", return_value=mock_context
    )
    return mock_context  # Return the context manager mock


@pytest.fixture
def mock_db_init(mocker) -> tuple[MagicMock, MagicMock]:
    """Mocks get_engine and create_db_and_tables."""
    mock_engine = MagicMock(name="MockEngine")
    mock_get_engine = mocker.patch(
        "reg_agent.pipelines.ingestion.loader.get_engine", return_value=mock_engine
    )
    mock_create_tables = mocker.patch(
        "reg_agent.pipelines.ingestion.loader.create_db_and_tables"
    )
    return mock_get_engine, mock_create_tables


# Helper function (remains largely the same)
def _create_dummy_files(
    base_dir: Path, file_specs: list[tuple[str, str]]
) -> list[Path]:
    """Helper to create dummy files/directories."""
    created_paths = []
    for rel_path_str, content in file_specs:
        file_path = base_dir / rel_path_str
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure content is bytes for blob consistency if needed
        if isinstance(content, str):
            file_path.write_text(content, encoding="utf-8")
        else:
            file_path.write_bytes(content)
        created_paths.append(file_path)
        # Add a tiny delay if distinct modification times are critical (usually not for mocks)
        # time.sleep(0.01)
    # Return absolute paths for consistency with loader logic
    return [p.resolve() for p in created_paths]


# --- Refactored Tests ---


def test_ingest_files_happy_path(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,
):
    """Test basic ingestion with mocks, checking calls and object creation."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_ingest.db"  # Path is still passed but used by mocks

    # Create dummy files
    file_specs = [
        ("file1.txt", "content1"),
        ("subdir/file2.pdf", "pdf content"),  # Changed to pdf for OCR test
        ("file3.log", "log content"),
    ]
    expected_paths = _create_dummy_files(source_dir, file_specs)

    # Configure mocks
    mock_ocr_service.extract_markdown_from_file.side_effect = (
        lambda p: "Extracted Markdown" if p.suffix == ".pdf" else None
    )

    # Run ingestion
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    mock_get_engine, mock_create_tables = mock_db_init
    # 1. Check DB initialization calls
    mock_get_engine.assert_called_once_with(db_file=db_file)
    mock_create_tables.assert_called_once_with(mock_get_engine.return_value)

    # 2. Check session management calls
    mock_session_context.__enter__.assert_called_once()
    mock_session_context.__exit__.assert_called_once()

    # 3. Check FileRepository calls
    # exists_by_source_path should be called for each file
    assert mock_file_repository.exists_by_source_path.call_count == len(expected_paths)
    expected_exists_calls = [call(str(p)) for p in expected_paths]
    mock_file_repository.exists_by_source_path.assert_has_calls(
        expected_exists_calls, any_order=True
    )

    # add should be called for each file (since exists returns False)
    assert mock_file_repository.add.call_count == len(expected_paths)

    # 4. Check OcrService calls (only for PDF)
    pdf_path = next(p for p in expected_paths if p.suffix == ".pdf")
    # non_pdf_paths = [p for p in expected_paths if p.suffix != ".pdf"]
    # Check that extract_markdown_from_file was called for the PDF path.
    # Since ocr_available is True, it will be called for all files,
    # but the service itself filters non-PDFs.
    mock_ocr_service.extract_markdown_from_file.assert_any_call(pdf_path)
    # Verify it was called for all files as ocr_available was True
    assert mock_ocr_service.extract_markdown_from_file.call_count == len(expected_paths)

    # 5. Verify the objects added to the repository
    added_records_args = [c.args[0] for c in mock_file_repository.add.call_args_list]
    assert len(added_records_args) == len(expected_paths)

    # Check details of one record (e.g., the PDF one)
    pdf_record_arg = next(
        r for r in added_records_args if r.source_path == str(pdf_path)
    )
    assert isinstance(pdf_record_arg, FileRecord)
    assert pdf_record_arg.source_path == str(pdf_path)
    assert pdf_record_arg.filename == pdf_path.name
    assert pdf_record_arg.blob == b"pdf content"
    assert pdf_record_arg.extracted_text == "Extracted Markdown"
    assert pdf_record_arg.size_bytes == len(b"pdf content")
    assert isinstance(pdf_record_arg.last_modified_ts, datetime.datetime)

    # Check details of a non-PDF record
    txt_path = next(p for p in expected_paths if p.suffix == ".txt")
    txt_record_arg = next(
        r for r in added_records_args if r.source_path == str(txt_path)
    )
    assert isinstance(txt_record_arg, FileRecord)
    assert txt_record_arg.source_path == str(txt_path)
    assert txt_record_arg.filename == txt_path.name
    assert txt_record_arg.blob == b"content1"
    assert txt_record_arg.extracted_text is None  # No OCR for non-PDF
    assert txt_record_arg.size_bytes == len(b"content1")


def test_ingest_files_duplicates_skipped(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,  # Even if not used directly, needs to be mocked
    caplog,
):
    """Test that existing files are skipped using mocks."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_duplicates.db"

    # Create one dummy file
    file_specs = [("file1.txt", "initial content")]
    expected_paths = _create_dummy_files(source_dir, file_specs)
    file_path_str = str(expected_paths[0])

    # --- Configure Mocks ---
    # Simulate the file existing
    mock_file_repository.exists_by_source_path.return_value = True

    # --- Run Ingestion ---
    caplog.set_level("DEBUG")  # To check skip message
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    mock_get_engine, mock_create_tables = mock_db_init
    # 1. Check DB initialization calls (still happens)
    mock_get_engine.assert_called_once_with(db_file=db_file)
    mock_create_tables.assert_called_once_with(mock_get_engine.return_value)

    # 2. Check session management calls (still happens)
    mock_session_context.__enter__.assert_called_once()
    mock_session_context.__exit__.assert_called_once()

    # 3. Check FileRepository calls
    # exists_by_source_path should be called once
    mock_file_repository.exists_by_source_path.assert_called_once_with(file_path_str)
    # add should NOT be called
    mock_file_repository.add.assert_not_called()

    # 4. Check OcrService calls (should not be called if file exists)
    mock_ocr_service.extract_markdown_from_file.assert_not_called()

    # 5. Check logs for skip message
    # Corrected log check format for structlog output
    # We expect the message and the path key-value pair in the log record text
    assert "Skipped existing file" in caplog.text
    # Check for the path string representation, accounting for potential escaping issues
    # A simpler check might be just looking for the filename if paths are tricky
    assert repr(file_path_str) in caplog.text or file_path_str in caplog.text


def test_ingest_files_empty_directory(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,
):
    """Test ingestion with an empty source directory using mocks."""
    source_dir = tmp_path / "empty_source"
    source_dir.mkdir()  # Ensure directory exists but is empty
    db_file = tmp_path / "test_empty.db"

    # --- Run Ingestion ---
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    mock_get_engine, mock_create_tables = mock_db_init
    # 1. Check DB initialization calls (should still happen)
    mock_get_engine.assert_called_once_with(db_file=db_file)
    mock_create_tables.assert_called_once_with(mock_get_engine.return_value)

    # 2. Check session management calls (should still happen)
    mock_session_context.__enter__.assert_called_once()
    mock_session_context.__exit__.assert_called_once()

    # 3. Check FileRepository calls (should NOT be called)
    mock_file_repository.exists_by_source_path.assert_not_called()
    mock_file_repository.add.assert_not_called()

    # 4. Check OcrService calls (should NOT be called)
    mock_ocr_service.extract_markdown_from_file.assert_not_called()


# test_ingest_files_nonexistent_directory - Still valid, doesn't hit mocks


# Keep this test as it doesn't involve the database interaction part
def test_ingest_files_nonexistent_directory(tmp_path, caplog):
    """Test ingestion with a source directory that does not exist."""
    source_dir = tmp_path / "nonexistent_source"
    db_file = tmp_path / "test_nonexistent.db"

    # Ensure the directory does not exist
    assert not source_dir.exists()

    # Capture log messages
    caplog.set_level("ERROR")

    ingest_files(source_dir, db_file=db_file)

    # Verify an error was logged
    assert "Source directory does not exist" in caplog.text

    # Verify the database file might not even be created or is empty if created
    # We don't check the DB file directly in unit tests anymore


# TODO: Add tests for:
# - Skipping duplicates (mock exists_by_source_path returning True)
# - Empty source directory (check mocks aren't called unnecessarily)
# - OCR Service unavailable (mock converter=None)
# - OCR Service fails during extraction (mock extract_markdown_from_file raises Exception)
# - OS Error reading file
# - DB error during get_engine or create_tables
# - DB error during session commit (mock session.__exit__ raises Exception)


def test_ingest_files_db_error_on_connect(tmp_path, mocker, caplog):
    """Test handling error when get_engine fails."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    _create_dummy_files(source_dir, [("file1.txt", "content")])  # Need some files
    db_file = tmp_path / "test_dberror_connect.db"

    # Mock get_engine to raise an exception
    mock_get_engine = mocker.patch(
        "reg_agent.pipelines.ingestion.loader.get_engine",
        side_effect=Exception("Simulated DB connection error"),
    )
    # Also mock create_db_and_tables so it's not called if get_engine fails
    mock_create_tables = mocker.patch(
        "reg_agent.pipelines.ingestion.loader.create_db_and_tables"
    )
    # Mock get_session so it's not called
    mock_get_session = mocker.patch("reg_agent.pipelines.ingestion.loader.get_session")

    caplog.set_level("ERROR")
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    # 1. Check get_engine was called
    mock_get_engine.assert_called_once_with(db_file=db_file)
    # 2. Check create_tables was NOT called because get_engine failed
    mock_create_tables.assert_not_called()
    # 3. Check get_session was NOT called
    mock_get_session.assert_not_called()
    # 4. Check error log
    assert "Failed to initialize database engine or tables" in caplog.text
    assert "Simulated DB connection error" in caplog.text


# test_ingest_files_general_exception_outer - Refactor Needed (mock session commit/exit)


def test_ingest_files_session_commit_error(
    tmp_path,
    mock_db_init,  # Need this for setup
    mock_session_context,  # Need the context mock
    mock_file_repository,  # Need this as it's used
    mock_ocr_service,  # Need this as it's used
    caplog,
):
    """Test handling error during session commit (mocking session exit)."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_commit_error.db"
    _create_dummy_files(source_dir, [("file1.txt", "content")])

    # Configure mocks
    mock_file_repository.exists_by_source_path.return_value = (
        False  # File needs processing
    )
    mock_ocr_service.extract_markdown_from_file.return_value = None

    # Mock the session context manager's exit to raise an error
    mock_session_context.__exit__.side_effect = Exception("Simulated commit error")

    caplog.set_level("ERROR")
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    mock_get_engine, mock_create_tables = mock_db_init
    # 1. Check DB initialization calls
    mock_get_engine.assert_called_once_with(db_file=db_file)
    mock_create_tables.assert_called_once_with(mock_get_engine.return_value)

    # 2. Check session management calls
    mock_session_context.__enter__.assert_called_once()
    mock_session_context.__exit__.assert_called_once()  # Exit is called, but raises error

    # 3. Check repository calls (add should have been called)
    mock_file_repository.exists_by_source_path.assert_called_once()
    mock_file_repository.add.assert_called_once()  # Add was attempted before commit failure

    # 4. Check error log for the session commit error
    assert "Database session/commit error during ingestion" in caplog.text
    assert "Simulated commit error" in caplog.text


# --- New Tests for Error Conditions ---


def test_ingest_files_ocr_service_unavailable(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,
    caplog,
):
    """Test ingestion when OcrService converter is not initialized."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_ocr_unavailable.db"
    _create_dummy_files(source_dir, [("file1.pdf", "pdf content")])

    # Configure mocks
    mock_ocr_service.converter = None  # Simulate init failure
    mock_file_repository.exists_by_source_path.return_value = False

    caplog.set_level("WARNING")
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    # 1. Check warning log
    assert "OCR Service converter not initialized" in caplog.text

    # 2. Check OCR was not called
    mock_ocr_service.extract_markdown_from_file.assert_not_called()

    # 3. Check FileRepository add was called (file should still be added without text)
    mock_file_repository.add.assert_called_once()
    added_record = mock_file_repository.add.call_args[0][0]
    assert isinstance(added_record, FileRecord)
    assert added_record.extracted_text is None


def test_ingest_files_ocr_extraction_fails(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,
    caplog,
):
    """Test ingestion when OcrService fails during extraction."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_ocr_fail.db"
    pdf_paths = _create_dummy_files(source_dir, [("file1.pdf", "pdf content")])
    pdf_path_str = str(pdf_paths[0])

    # Configure mocks
    mock_ocr_service.converter = True  # Service is available
    mock_ocr_service.extract_markdown_from_file.side_effect = Exception(
        "Simulated OCR Error"
    )
    mock_file_repository.exists_by_source_path.return_value = False

    caplog.set_level("WARNING")
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    # 1. Check OCR was called (attempted)
    mock_ocr_service.extract_markdown_from_file.assert_called_once_with(pdf_paths[0])

    # 2. Check warning log
    # Check caplog.text for core message and error due to issues checking caplog.records
    assert "Failed to extract text from file" in caplog.text
    assert "Simulated OCR Error" in caplog.text

    # 3. Check FileRepository add was called (file added without text)
    mock_file_repository.add.assert_called_once()
    added_record = mock_file_repository.add.call_args[0][0]
    assert isinstance(added_record, FileRecord)
    assert added_record.source_path == pdf_path_str
    assert added_record.extracted_text is None


def test_ingest_files_os_error_reading_file(
    tmp_path,
    mock_db_init,
    mock_session_context,
    mock_file_repository,
    mock_ocr_service,  # Still needed for setup
    mocker,  # Need mocker to patch open
    caplog,
):
    """Test handling OSError when opening/reading a file."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_os_error.db"
    file_paths = _create_dummy_files(source_dir, [("file1.txt", "content")])

    # Configure mocks
    mock_file_repository.exists_by_source_path.return_value = False

    # Patch built-in open to raise OSError
    mock_open = mocker.patch(
        "builtins.open", side_effect=OSError("Simulated permission denied")
    )

    caplog.set_level("ERROR")
    ingest_files(source_dir, db_file=db_file)

    # --- Assertions ---
    # 1. Check open was called (attempted)
    mock_open.assert_called_once_with(file_paths[0], "rb")

    # 2. Check FileRepository add was NOT called
    mock_file_repository.add.assert_not_called()

    # 3. Check error log
    # Check caplog.text for core message and error
    assert "OS Error processing file" in caplog.text
    assert "Simulated permission denied" in caplog.text
