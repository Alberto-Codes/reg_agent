# tests/pipelines/ingestion/test_run.py

from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from sqlalchemy.engine import Engine

# Module to test - Import will happen inside tests
# from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline, DEFAULT_DB_FILE

MOCK_SOURCE_DIR = "/mock/source"
MOCK_DB_FILE = "/mock/db.sqlite"

# --- Fixtures ---


@pytest.fixture()
def mock_dependencies(mocker):
    """Mocks all external dependencies used by run_ingestion_pipeline."""
    mocks = {}
    # Import necessary items for fixture setup *only*
    from reg_agent.pipelines.ingestion.run import DEFAULT_DB_FILE

    # Mock Path (Patching where used in run.py)
    mock_p = mocker.patch("reg_agent.pipelines.ingestion.run.Path")
    mock_source_instance = MagicMock(spec=Path)
    mock_source_instance.is_dir.return_value = True
    mock_source_instance.__str__.return_value = MOCK_SOURCE_DIR
    mock_default_db_instance = MagicMock(spec=Path)
    mock_default_db_instance.__str__.return_value = str(DEFAULT_DB_FILE)
    mock_db_file_instance = MagicMock(spec=Path)
    mock_db_file_instance.__str__.return_value = MOCK_DB_FILE

    def path_side_effect(path_arg):
        # Make Path() return specific mocks based on input
        if path_arg == MOCK_SOURCE_DIR:
            return mock_source_instance
        elif path_arg == MOCK_DB_FILE:
            return mock_db_file_instance
        elif path_arg == DEFAULT_DB_FILE:
            return mock_default_db_instance
        else:
            return MagicMock(spec=Path, __str__=lambda: str(path_arg))

    mock_p.side_effect = path_side_effect
    mocks["Path"] = mock_p
    mocks["source_path_instance"] = mock_source_instance
    mocks["db_path_instance"] = mock_db_file_instance
    mocks["default_db_path_instance"] = mock_default_db_instance

    # Mock DB setup (Patching where used in run.py)
    mocks["engine"] = MagicMock(spec=Engine)
    mocks["get_engine"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.get_engine", return_value=mocks["engine"]
    )
    mocks["create_db"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.create_db_and_tables"
    )

    # Mock Tasks (Patching where used in run.py)
    mocks["run_task_1"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.run_task_1", return_value=(10, 2, 0)
    )
    mocks["run_task_2"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.run_task_2", return_value=(8, 7, 1, 0)
    )
    t3_result = (5, 4, 1)
    mocks["run_task_3_async"] = AsyncMock(return_value=t3_result)
    mocker.patch(
        "reg_agent.pipelines.ingestion.run.run_task_3", new=mocks["run_task_3_async"]
    )
    # Patch asyncio.run where it's used in run.py
    mocks["asyncio_run"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.asyncio.run", return_value=t3_result
    )

    # Mock log (Patching where used in run.py)
    mocks["log"] = MagicMock()
    mocker.patch("reg_agent.pipelines.ingestion.run.log", mocks["log"])

    # Mock decorator (Patching where used in run.py)
    def passthrough_decorator(task_name):
        def decorator(func):
            return func

        return decorator

    mocker.patch(
        "reg_agent.pipelines.ingestion.run.log_task_duration", passthrough_decorator
    )

    return mocks


# --- Test Cases ---


def test_run_pipeline_success(mock_dependencies):
    """Test the successful run of the entire pipeline."""
    from reg_agent.pipelines.ingestion.run import (
        Path,
        run_ingestion_pipeline,
    )  # Import Path locally too

    mock_p_constructor = mock_dependencies["Path"]
    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    _mock_t3_async = mock_dependencies["run_task_3_async"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]
    db_path_instance = mock_dependencies["db_path_instance"]

    # Use Path objects (which will now hit the mock constructor)
    source_dir_obj = Path(MOCK_SOURCE_DIR)
    db_file_obj = Path(MOCK_DB_FILE)

    run_ingestion_pipeline(source_dir=source_dir_obj, db_file=db_file_obj)

    # Check setup calls
    mock_p_constructor.assert_any_call(MOCK_SOURCE_DIR)
    mock_p_constructor.assert_any_call(MOCK_DB_FILE)
    source_path_instance.is_dir.assert_called_once()
    mock_get_engine.assert_called_once_with(db_file=db_path_instance)
    mock_create_db.assert_called_once_with(mock_engine)

    # Check task calls
    mock_t1.assert_called_once_with(mock_engine, source_path_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_asyncio_run.assert_called_once()

    # Check logging
    mock_log.info.assert_any_call(
        "Pipeline run details",
        source_dir=str(source_path_instance),
        db_file=str(db_path_instance),
    )
    mock_log.info.assert_any_call(
        "Task 1 (Create Records) summary", inserted=10, skipped=2, errors=0
    )
    mock_log.info.assert_any_call(
        "Task 2 (OCR) summary", found=8, success=7, skipped=1, errors=0
    )
    mock_log.info.assert_any_call(
        "Task 3 (Metadata) summary", found=5, success=4, errors=1
    )
    mock_log.info.assert_any_call(
        "Pipeline task summaries complete.",
        task1_results=(10, 2, 0),
        task2_results=(8, 7, 1, 0),
        task3_results=(5, 4, 1),
    )
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()


def test_run_pipeline_invalid_source_dir(mock_dependencies):
    """Test pipeline halts if source directory is invalid."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    source_path_instance.is_dir.return_value = False

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_log.error.assert_called_once_with(
        "Source directory does not exist or is not a directory. Halting pipeline.",
        path=str(source_path_instance),
    )
    mock_get_engine.assert_not_called()
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()


def test_run_pipeline_get_engine_fails(mock_dependencies):
    """Test pipeline halts if get_engine fails."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    mock_get_engine.side_effect = ValueError("DB connection failed")

    # Test with default db_file path
    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_get_engine.assert_called_once_with(db_file=ANY)
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="DB connection failed",
    )
    mock_create_db.assert_not_called()
    mock_t1.assert_not_called()


def test_run_pipeline_create_db_fails(mock_dependencies):
    """Test pipeline halts if create_db_and_tables fails."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_get_engine = mock_dependencies["get_engine"]
    mock_create_db = mock_dependencies["create_db"]
    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    mock_create_db.side_effect = RuntimeError("Table creation error")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_get_engine.assert_called_once_with(db_file=ANY)
    mock_create_db.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "Failed to initialize database engine or tables. Halting pipeline.",
        error="Table creation error",
    )
    mock_t1.assert_not_called()


def test_run_pipeline_task1_fails(mock_dependencies):
    """Test pipeline handles exception during Task 1."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    mock_t1.side_effect = IOError("Cannot read file")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_t1.assert_called_once_with(mock_engine, source_path_instance)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="Cannot read file",
    )
    mock_t2.assert_not_called()
    mock_asyncio_run.assert_not_called()


def test_run_pipeline_task2_fails(mock_dependencies):
    """Test pipeline handles exception during Task 2."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    mock_t2.side_effect = ValueError("OCR Engine unavailable")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_t1.assert_called_once_with(mock_engine, source_path_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="OCR Engine unavailable",
    )
    mock_asyncio_run.assert_not_called()


def test_run_pipeline_task3_fails(mock_dependencies):
    """Test pipeline handles exception during Task 3 (asyncio.run)."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_engine = mock_dependencies["engine"]
    mock_t1 = mock_dependencies["run_task_1"]
    mock_t2 = mock_dependencies["run_task_2"]
    _mock_t3_async = mock_dependencies["run_task_3_async"]
    mock_asyncio_run = mock_dependencies["asyncio_run"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    mock_asyncio_run.side_effect = ConnectionRefusedError("LLM endpoint down")

    run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_t1.assert_called_once_with(mock_engine, source_path_instance)
    mock_t2.assert_called_once_with(mock_engine)
    mock_asyncio_run.assert_called_once()
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline execution.",
        error="LLM endpoint down",
    )
