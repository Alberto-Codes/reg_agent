# tests/pipelines/ingestion/test_run.py

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

from sqlalchemy.engine import Engine

# Module to test
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline, DEFAULT_DB_FILE

MOCK_SOURCE_DIR = "/mock/source"
MOCK_DB_FILE = "/mock/db.sqlite"

# --- Fixtures ---

@pytest.fixture
def mock_path(mocker):
    """Mocks pathlib.Path methods."""
    mock_p = mocker.patch("reg_agent.pipelines.ingestion.run.Path")
    # Simulate a directory that exists for the source_dir check
    mock_instance = mock_p.return_value
    mock_instance.is_dir.return_value = True
    mock_instance.__str__.return_value = MOCK_SOURCE_DIR # For logging
    return mock_p, mock_instance

@pytest.fixture
def mock_db_setup(mocker):
    """Mocks database setup functions."""
    mock_engine = MagicMock(spec=Engine)
    mock_get_engine = mocker.patch("reg_agent.pipelines.ingestion.run.get_engine", return_value=mock_engine)
    mock_create_db = mocker.patch("reg_agent.pipelines.ingestion.run.create_db_and_tables")
    return mock_get_engine, mock_create_db, mock_engine

@pytest.fixture
def mock_tasks(mocker):
    """Mocks the task runner functions."""
    mock_t1 = mocker.patch("reg_agent.pipelines.ingestion.run.run_task_1", return_value=(10, 2, 0)) # inserted, skipped, errors
    mock_t2 = mocker.patch("reg_agent.pipelines.ingestion.run.run_task_2", return_value=(8, 7, 1, 0)) # found, success, skipped, errors
    # Mock run_task_3 to be an async function that asyncio.run can execute
    mock_t3_async_result = (5, 4, 1) # found, success, errors
    mock_t3_async = AsyncMock(return_value=mock_t3_async_result)
    mocker.patch("reg_agent.pipelines.ingestion.run.run_task_3", new=mock_t3_async)
    # We also need to mock asyncio.run used to call task 3
    mock_asyncio_run = mocker.patch("reg_agent.pipelines.ingestion.run.asyncio.run", return_value=mock_t3_async_result)

    return mock_t1, mock_t2, mock_t3_async, mock_asyncio_run

@pytest.fixture
def mock_log(mocker):
    """Mocks the logger object."""
    mock_logger = MagicMock()
    mocker.patch("reg_agent.pipelines.ingestion.run.log", mock_logger)
    return mock_logger

# --- Test Cases ---

def test_run_pipeline_success(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test the successful run of the entire pipeline."""
    mock_p, mock_source_path_instance = mock_path
    mock_get_engine, mock_create_db, mock_engine = mock_db_setup
    mock_t1, mock_t2, mock_t3_async, mock_asyncio_run = mock_tasks

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR), db_file=Path(MOCK_DB_FILE))

    # Check setup
    mock_p.assert_any_call(MOCK_SOURCE_DIR)
    mock_p.assert_any_call(MOCK_DB_FILE)
    mock_source_path_instance.is_dir.assert_called_once()
    mock_get_engine.assert_called_once_with(db_file=mock_p.return_value)
    mock_create_db.assert_called_once_with(mock_engine)

    # Check task calls
    mock_t1.assert_called_once_with(mock_engine, mock_p.return_value)
    mock_t2.assert_called_once_with(mock_engine)
    # Check that asyncio.run was called with the result of calling run_task_3
    mock_asyncio_run.assert_called_once_with(mock_t3_async(mock_engine))

    # Check logging (basic checks for key messages)
    mock_log.info.assert_any_call("Pipeline run details", source_dir=MOCK_SOURCE_DIR, db_file=MOCK_DB_FILE)
    mock_log.info.assert_any_call("Task 1 (Create Records) summary", inserted=10, skipped=2, errors=0)
    mock_log.info.assert_any_call("Task 2 (OCR) summary", found=8, success=7, skipped=1, errors=0)
    mock_log.info.assert_any_call("Task 3 (Metadata) summary", found=5, success=4, errors=1)
    mock_log.info.assert_any_call("Pipeline task summaries complete.", task1_results=(10, 2, 0), task2_results=(8, 7, 1, 0), task3_results=(5, 4, 1))
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()

def test_run_pipeline_invalid_source_dir(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline halts if source directory is invalid."""
    mock_p, mock_source_path_instance = mock_path
    mock_get_engine, mock_create_db, _ = mock_db_setup
    mock_t1, mock_t2, _, _ = mock_tasks

    mock_source_path_instance.is_dir.return_value = False # Simulate invalid dir

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_source_path_instance.is_dir.assert_called_once()
    mock_log.error.assert_called_once_with(
        "Source directory does not exist or is not a directory. Halting pipeline.",
        path=MOCK_SOURCE_DIR
    )
    # Ensure DB setup and tasks were not called
    mock_get_engine.assert_not_called()
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()
    mock_t2.assert_not_called()

def test_run_pipeline_get_engine_fails(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline halts if get_engine fails."""
    mock_get_engine, mock_create_db, _ = mock_db_setup
    mock_t1, _, _, _ = mock_tasks
    mock_get_engine.side_effect = ValueError("DB connection failed")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_get_engine.assert_called_once()
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="DB connection failed",
    )
    # Ensure subsequent steps were not called
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()

def test_run_pipeline_create_db_fails(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline halts if create_db_and_tables fails."""
    mock_get_engine, mock_create_db, mock_engine = mock_db_setup
    mock_t1, _, _, _ = mock_tasks
    mock_create_db.side_effect = RuntimeError("Table creation error")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_get_engine.assert_called_once()
    mock_create_db.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="Table creation error",
    )
    # Ensure tasks were not called
    mock_t1.assert_not_called()

def test_run_pipeline_task1_fails(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline handles exception during Task 1."""
    _, _, mock_engine = mock_db_setup
    mock_t1, mock_t2, _, mock_asyncio_run = mock_tasks
    mock_t1.side_effect = IOError("Cannot read file")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_t1.assert_called_once_with(mock_engine, mock_path[1])
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="Cannot read file"
    )
    # Ensure subsequent tasks were not called
    mock_t2.assert_not_called()
    mock_asyncio_run.assert_not_called()

def test_run_pipeline_task2_fails(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline handles exception during Task 2."""
    _, _, mock_engine = mock_db_setup
    mock_t1, mock_t2, _, mock_asyncio_run = mock_tasks
    mock_t2.side_effect = ValueError("OCR Engine unavailable")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_t1.assert_called_once()
    mock_t2.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="OCR Engine unavailable"
    )
    # Ensure subsequent tasks were not called
    mock_asyncio_run.assert_not_called()

def test_run_pipeline_task3_fails(mock_path, mock_db_setup, mock_tasks, mock_log):
    """Test pipeline handles exception during Task 3 (asyncio.run)."""
    _, _, mock_engine = mock_db_setup
    mock_t1, mock_t2, mock_t3_async, mock_asyncio_run = mock_tasks
    mock_asyncio_run.side_effect = ConnectionRefusedError("LLM endpoint down")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    mock_t1.assert_called_once()
    mock_t2.assert_called_once()
    mock_asyncio_run.assert_called_once_with(mock_t3_async(mock_engine))
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="LLM endpoint down"
    ) 