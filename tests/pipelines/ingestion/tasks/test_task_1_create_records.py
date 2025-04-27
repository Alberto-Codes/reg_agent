# tests/pipelines/ingestion/tasks/test_task_1_create_records.py

import pytest
from pathlib import Path
import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import Engine
from sqlmodel import Session

from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.pipelines.ingestion.tasks.task_1_create_records import run_task_1

# from tests.core.db.test_connection import test_engine # noqa: F401

@pytest.fixture
def mock_session(mocker):
    """Fixture to mock the get_session context manager and the session object."""
    mock_sess = mocker.MagicMock(spec=Session)
    # Mock the context manager
    mock_context = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_1_create_records.get_session")
    # Make the context manager return the mocked session
    mock_context.return_value.__enter__.return_value = mock_sess
    return mock_sess

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

def test_run_task_1_creates_new_records(test_engine: Engine, source_test_dir: Path, mock_session: MagicMock, mocker):
    """Test that Task 1 correctly identifies and stages new file records."""
    # Mock the FileRepository methods used within the task
    mock_repo_instance = mocker.MagicMock(spec=FileRepository)
    mock_repo_instance.exists_by_source_path.return_value = False # Assume no files exist initially
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_1_create_records.FileRepository",
        return_value=mock_repo_instance
    )

    inserted, skipped, errors = run_task_1(test_engine, source_test_dir)

    assert inserted == 3
    assert skipped == 0
    assert errors == 0
    assert mock_repo_instance.exists_by_source_path.call_count == 3
    assert mock_session.add.call_count == 3 # Check that add was called for each new file

def test_run_task_1_skips_existing_records(test_engine: Engine, source_test_dir: Path, mock_session: MagicMock, mocker):
    """Test that Task 1 skips files if exists_by_source_path returns True."""
    mock_repo_instance = mocker.MagicMock(spec=FileRepository)
    # Simulate that all files already exist in the DB
    mock_repo_instance.exists_by_source_path.return_value = True
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_1_create_records.FileRepository",
        return_value=mock_repo_instance
    )

    inserted, skipped, errors = run_task_1(test_engine, source_test_dir)

    assert inserted == 0
    assert skipped == 3
    assert errors == 0
    assert mock_repo_instance.exists_by_source_path.call_count == 3
    mock_session.add.assert_not_called() # No records should be added

def test_run_task_1_handles_os_error(test_engine: Engine, source_test_dir: Path, mock_session: MagicMock, mocker):
    """Test Task 1 error handling when file access causes an OSError."""
    mock_repo_instance = mocker.MagicMock(spec=FileRepository)
    mock_repo_instance.exists_by_source_path.return_value = False
    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_1_create_records.FileRepository",
        return_value=mock_repo_instance
    )

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

    mocker.patch.object(Path, 'stat', mock_stat)

    inserted, skipped, errors = run_task_1(test_engine, source_test_dir)

    assert inserted == 2 # First and third file should be processed
    assert skipped == 0
    assert errors == 1   # One error occurred
    assert mock_session.add.call_count == 2

def test_run_task_1_handles_general_exception(test_engine: Engine, source_test_dir: Path, mock_session: MagicMock, mocker):
    """Test Task 1 error handling for unexpected exceptions."""
    mock_repo_instance = mocker.MagicMock(spec=FileRepository)
    # Let the first file exist, raise exception on second, skip third
    def side_effect(path_str):
        if "file1.txt" in path_str:
            return False
        elif "file2.pdf" in path_str:
             raise ValueError("Unexpected value error") # Simulate unexpected error
        return False # Process file3
    mock_repo_instance.exists_by_source_path.side_effect = side_effect

    mocker.patch(
        "reg_agent.pipelines.ingestion.tasks.task_1_create_records.FileRepository",
        return_value=mock_repo_instance
    )

    inserted, skipped, errors = run_task_1(test_engine, source_test_dir)

    assert inserted == 2 # file1 and file3 processed
    assert skipped == 0
    assert errors == 1   # Error on file2
    assert mock_repo_instance.exists_by_source_path.call_count == 3
    assert mock_session.add.call_count == 2 