# tests/pipelines/ingestion/test_run.py

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

from sqlalchemy.engine import Engine

# Module to test
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline, DEFAULT_DB_FILE
# Import task modules to patch them directly if needed
# from reg_agent.pipelines.ingestion import tasks

MOCK_SOURCE_DIR = "/mock/source"
MOCK_DB_FILE = "/mock/db.sqlite"

# --- Fixtures ---

@pytest.fixture(autouse=True)
def mock_dependencies(mocker):
    """Mocks all external dependencies used by run_ingestion_pipeline."""
    mocks = {}

    # Mock Path
    mock_p = mocker.patch("pathlib.Path") # Patching standard library directly
    mock_instance = MagicMock(spec=Path)
    mock_instance.is_dir.return_value = True
    mock_instance.__str__.return_value = MOCK_SOURCE_DIR
    def path_side_effect(path_arg):
        if path_arg == MOCK_SOURCE_DIR:
            mock_instance.name = MOCK_SOURCE_DIR.split("/")[-1]
            return mock_instance
        elif path_arg == MOCK_DB_FILE or path_arg == DEFAULT_DB_FILE:
            db_mock_instance = MagicMock(spec=Path)
            db_mock_instance.__str__.return_value = str(path_arg)
            db_mock_instance.name = str(path_arg).split("/")[-1]
            return db_mock_instance
        else:
            default_mock = MagicMock(spec=Path)
            default_mock.__str__.return_value = str(path_arg)
            return default_mock
    mock_p.side_effect = path_side_effect
    mocks["Path"] = mock_p
    mocks["source_path_instance"] = mock_instance

    # Mock DB setup
    mocks["engine"] = MagicMock(spec=Engine)
    # Patch where functions are defined/imported from
    mocks["get_engine"] = mocker.patch("reg_agent.core.db.connection.get_engine", return_value=mocks["engine"])
    mocks["create_db"] = mocker.patch("reg_agent.core.db.connection.create_db_and_tables")

    # Mock Tasks (patching functions in their actual module files)
    mocks["run_task_1"] = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_1_create_records.run_task_1", return_value=(10, 2, 0))
    mocks["run_task_2"] = mocker.patch("reg_agent.pipelines.ingestion.tasks.task_2_ocr.run_task_2", return_value=(8, 7, 1, 0))
    t3_result = (5, 4, 1)
    # Patch the async function in its module
    mocks["run_task_3_async"] = AsyncMock(return_value=t3_result)
    mocker.patch("reg_agent.pipelines.ingestion.tasks.task_3_metadata.run_task_3", new=mocks["run_task_3_async"])
    # Patch asyncio.run where it's used in the run module
    mocks["asyncio_run"] = mocker.patch("reg_agent.pipelines.ingestion.run.asyncio.run", return_value=t3_result)

    # Mock log
    mocks["log"] = MagicMock()
    mocker.patch("reg_agent.pipelines.ingestion.run.log", mocks["log"])

    # Mock decorator (still potentially useful to ensure it doesn't interfere)
    def passthrough_decorator(task_name):
        def decorator(func):
            return func
        return decorator
    # Patch decorator where it's defined
    mocker.patch("reg_agent.utils.timing.log_task_duration", passthrough_decorator)

    return mocks


# --- Test Cases ---

def test_run_pipeline_success(mock_dependencies):
    """Test the successful run of the entire pipeline."""
    # Extract mocks from the combined fixture
    mock_p_constructor = mock_dependencies["Path"]
    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_t3_async = mock_dependencies["run_task_3_async"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]

    # Use Path objects as the function expects
    source_dir_obj = Path(MOCK_SOURCE_DIR)
    db_file_obj = Path(MOCK_DB_FILE)

    run_ingestion_pipeline(source_dir=source_dir_obj, db_file=db_file_obj)

    # Check setup calls
    mock_p_constructor.assert_any_call(MOCK_SOURCE_DIR)
    mock_p_constructor.assert_any_call(MOCK_DB_FILE)
    # Get the instance returned by the mock constructor for source_dir
    source_dir_instance = mock_p_constructor(MOCK_SOURCE_DIR)
    db_file_instance = mock_p_constructor(MOCK_DB_FILE)
    source_dir_instance.is_dir.assert_called_once()
    mock_get_engine.assert_called_once_with(db_file=db_file_instance)
    mock_create_db.assert_called_once_with(mock_engine)

    # Check task calls
    mock_t1.assert_called_once_with(mock_engine, source_dir_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_t3_async_call = mock_t3_async(mock_engine) # Simulate the coro call
    mock_asyncio_run.assert_called_once_with(mock_t3_async_call)

    # Check logging
    mock_log.info.assert_any_call("Pipeline run details", source_dir=str(source_dir_instance), db_file=str(db_file_instance))
    mock_log.info.assert_any_call("Task 1 (Create Records) summary", inserted=10, skipped=2, errors=0)
    mock_log.info.assert_any_call("Task 2 (OCR) summary", found=8, success=7, skipped=1, errors=0)
    mock_log.info.assert_any_call("Task 3 (Metadata) summary", found=5, success=4, errors=1)
    mock_log.info.assert_any_call("Pipeline task summaries complete.", task1_results=(10, 2, 0), task2_results=(8, 7, 1, 0), task3_results=(5, 4, 1))
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()

def test_run_pipeline_invalid_source_dir(mock_dependencies):
    """Test pipeline halts if source directory is invalid."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]

    source_dir_instance = mock_p_constructor(MOCK_SOURCE_DIR)
    source_dir_instance.is_dir.return_value = False

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_dir_instance.is_dir.assert_called_once()
    mock_log.error.assert_called_once_with(
        "Source directory does not exist or is not a directory. Halting pipeline.",
        path=str(source_dir_instance)
    )
    mock_get_engine.assert_not_called()
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()

def test_run_pipeline_get_engine_fails(mock_dependencies):
    """Test pipeline halts if get_engine fails."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]

    mock_get_engine.side_effect = ValueError("DB connection failed")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    db_file_instance = mock_p_constructor(DEFAULT_DB_FILE)
    mock_get_engine.assert_called_once_with(db_file=db_file_instance)
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="DB connection failed",
    )
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()

def test_run_pipeline_create_db_fails(mock_dependencies):
    """Test pipeline halts if create_db_and_tables fails."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]

    mock_create_db.side_effect = RuntimeError("Table creation error")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    db_file_instance = mock_p_constructor(DEFAULT_DB_FILE)
    mock_get_engine.assert_called_once_with(db_file=db_file_instance)
    mock_create_db.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="Table creation error",
    )
    mock_t1.assert_not_called()

def test_run_pipeline_task1_fails(mock_dependencies):
    """Test pipeline handles exception during Task 1."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]

    mock_t1.side_effect = IOError("Cannot read file")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_dir_instance = mock_p_constructor(MOCK_SOURCE_DIR)
    mock_t1.assert_called_once_with(mock_engine, source_dir_instance)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="Cannot read file"
    )
    mock_t2.assert_not_called()
    mock_asyncio_run.assert_not_called()

def test_run_pipeline_task2_fails(mock_dependencies):
    """Test pipeline handles exception during Task 2."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]

    mock_t2.side_effect = ValueError("OCR Engine unavailable")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_dir_instance = mock_p_constructor(MOCK_SOURCE_DIR)
    mock_t1.assert_called_once_with(mock_engine, source_dir_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="OCR Engine unavailable"
    )
    mock_asyncio_run.assert_not_called()

def test_run_pipeline_task3_fails(mock_dependencies):
    """Test pipeline handles exception during Task 3 (asyncio.run)."""
    mock_p_constructor = mock_dependencies["Path"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_t3_async = mock_dependencies["run_task_3_async"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]

    mock_asyncio_run.side_effect = ConnectionRefusedError("LLM endpoint down")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_dir_instance = mock_p_constructor(MOCK_SOURCE_DIR)
    mock_t1.assert_called_once_with(mock_engine, source_dir_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_t3_async_call = mock_t3_async(mock_engine)
    mock_asyncio_run.assert_called_once_with(mock_t3_async_call)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="LLM endpoint down"
    ) 