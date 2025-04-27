# tests/pipelines/ingestion/tasks/test_task_1_create_records.py

from pathlib import Path
from unittest.mock import MagicMock

import pytest
# from sqlalchemy.engine import Engine # No longer needed
# from sqlmodel import Session # No longer needed

# Keep this for type hinting the mock
from reg_agent.core.db.repositories import DocumentRepository

# Import the task function
from reg_agent.pipelines.ingestion.tasks.task_1_create_records import run_task_1

# Import UoW for type hinting the mock
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork

# from tests.core.db.test_connection import test_engine # noqa: F401


@pytest.fixture
def mock_uow(mocker):
    """Fixture to mock the SqlModelUnitOfWork context manager and its repository."""
    # Mock the UoW class within the task module
    mock_uow_class = mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_1_create_records.SqlModelUnitOfWork"
    )

    # Create mock instances for the UoW context and the repository
    mock_uow_instance = MagicMock(spec=SqlModelUnitOfWork)
    mock_repo_instance = MagicMock(spec=DocumentRepository)

    # Configure the mock UoW instance to return the mock repo
    # when its 'documents' attribute is accessed
    mock_uow_instance.documents = mock_repo_instance

    # Configure the mocked UoW class's __enter__ to return the mock UoW instance
    mock_uow_class.return_value.__enter__.return_value = mock_uow_instance

    # Return the mock instances for use in tests
    return mock_uow_class, mock_uow_instance, mock_repo_instance


@pytest.fixture
def source_test_dir(tmp_path: Path) -> Path:
    """Creates a temporary source directory with some files."""
    source_dir = tmp_path / "task1_source"
    source_dir.mkdir()
    (source_dir / "file1.txt").write_text("content1")
    (source_dir / "file2.pdf").write_text("content2")
    subdir = source_dir / "subdir"
    subdir.mkdir()
    (subdir / "file3.log").write_text("log content")
    return source_dir


def test_run_task_1_creates_new_records(source_test_dir: Path, mock_uow):
    """Test that Task 1 correctly identifies and stages new file records using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow

    # Assume no files exist initially
    mock_repo_instance.exists_by_source_path.return_value = False

    # Run the task (no engine needed now)
    inserted, skipped, errors = run_task_1(source_test_dir)

    assert inserted == 3
    assert skipped == 0
    assert errors == 0
    # Check calls on the repository mock obtained via UoW
    assert mock_repo_instance.exists_by_source_path.call_count == 3
    assert mock_repo_instance.add.call_count == 3
    # Verify the UoW context manager was used
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()
    # Commit/Rollback checks are implicitly handled by UoW tests, focus here is on repo interaction


def test_run_task_1_skips_existing_records(source_test_dir: Path, mock_uow):
    """Test that Task 1 skips files if exists_by_source_path returns True using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow

    # Simulate that all files already exist in the DB
    mock_repo_instance.exists_by_source_path.return_value = True

    # Run the task
    inserted, skipped, errors = run_task_1(source_test_dir)

    assert inserted == 0
    assert skipped == 3
    assert errors == 0
    assert mock_repo_instance.exists_by_source_path.call_count == 3
    mock_repo_instance.add.assert_not_called()  # No records should be added
    # Verify the UoW context manager was used
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_1_handles_os_error(source_test_dir: Path, mock_uow, mocker):
    """Test Task 1 error handling when file access causes an OSError using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow

    mock_repo_instance.exists_by_source_path.return_value = False

    # Mock Path.stat to raise OSError for the second file it tries to stat
    original_stat = Path.stat
    stat_call_count = 0

    def mock_stat(self, *args, **kwargs):
        nonlocal stat_call_count
        stat_call_count += 1
        if stat_call_count == 2:
            raise OSError("Permission denied")
        # Call the original Path.stat for other files
        return original_stat(self, *args, **kwargs)

    mocker.patch.object(Path, "stat", mock_stat)

    # Run the task
    inserted, skipped, errors = run_task_1(source_test_dir)

    assert inserted == 2  # First and third file should be processed
    assert skipped == 0
    assert errors == 1  # One error occurred
    assert mock_repo_instance.add.call_count == 2
    # Verify the UoW context manager was used
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()


def test_run_task_1_handles_general_exception(source_test_dir: Path, mock_uow):
    """Test Task 1 error handling for unexpected exceptions using UoW."""
    mock_uow_class, mock_uow_instance, mock_repo_instance = mock_uow

    # Let the first file be processed, raise exception on second's existence check
    def side_effect(path_str):
        if "file1.txt" in path_str:
            return False  # Process file1
        elif "file2.pdf" in path_str:
            raise ValueError("Unexpected value error")  # Simulate unexpected error
        return False  # Process file3

    mock_repo_instance.exists_by_source_path.side_effect = side_effect

    # Run the task
    inserted, skipped, errors = run_task_1(source_test_dir)

    assert inserted == 2  # Corrected assertion: file1 and file3 processed
    assert skipped == 0
    assert errors == 1  # Error on file2
    # Here, error is on exists_by_source_path for file2, but the check for file3 still runs
    assert (
        mock_repo_instance.exists_by_source_path.call_count == 3
    )  # Corrected assertion: called for all 3 files
    assert (
        mock_repo_instance.add.call_count == 2
    )  # Corrected assertion: file1 and file3 added
    # Verify the UoW context manager was used
    mock_uow_class.assert_called_once()
    mock_uow_class.return_value.__enter__.assert_called_once()
    mock_uow_class.return_value.__exit__.assert_called_once()
