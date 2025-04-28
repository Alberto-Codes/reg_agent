# tests/pipelines/ingestion/test_run.py

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Removed: from sqlalchemy.engine import Engine

# Module to test - Import will happen inside tests
# from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline

MOCK_SOURCE_DIR = "/mock/source"
MOCK_DB_FILE = "/mock/db.sqlite"

# Expected success result from the graph
MOCK_GRAPH_SUCCESS_RESULT = {
    "task_1": {"inserted": 10, "skipped": 2, "errors": 0},
    "task_2": {"found": 8, "success": 7, "skipped": 1, "errors": 0},
    "task_3": {"found": 5, "success": 4, "errors": 1},
}

# --- Fixtures ---


@pytest.fixture()
def mock_dependencies(mocker):
    """Mocks external dependencies used by run_ingestion_pipeline."""
    mocks = {}
    # Import necessary items for fixture setup *only*
    from reg_agent.core.db.connection import DEFAULT_DB_FILE

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
        if path_arg == MOCK_SOURCE_DIR:
            return mock_source_instance
        elif path_arg == MOCK_DB_FILE:
            return mock_db_file_instance
        elif str(path_arg) == str(DEFAULT_DB_FILE):  # Compare strings for default
            return mock_default_db_instance
        else:
            return MagicMock(spec=Path, __str__=lambda: str(path_arg))

    mock_p.side_effect = path_side_effect
    mocks["Path"] = mock_p
    mocks["source_path_instance"] = mock_source_instance
    mocks["db_path_instance"] = mock_db_file_instance
    mocks["default_db_path_instance"] = mock_default_db_instance

    # Mock DB setup (Removed - happens inside graph execution)
    # mocks["engine"] = MagicMock(spec=Engine)
    # mocks["get_engine"] = mocker.patch(
    #     "reg_agent.pipelines.ingestion.run.get_engine", return_value=mocks["engine"]
    # )
    # mocks["create_db"] = mocker.patch(
    #     "reg_agent.pipelines.ingestion.run.create_db_and_tables"
    # )

    # Mock Tasks (Removed - called inside graph execution)
    # mocks["run_task_1"] = mocker.patch(...)
    # mocks["run_task_2"] = mocker.patch(...)
    # mocks["run_task_3_async"] = AsyncMock(...)
    # mocker.patch("reg_agent.pipelines.ingestion.run.run_task_3", ...)
    # mocks["asyncio_run"] = mocker.patch(...)

    # Mock the graph execution function (New)
    mocks["execute_graph"] = mocker.patch(
        "reg_agent.pipelines.ingestion.run.execute_ingestion_graph",
        new_callable=AsyncMock,
        return_value=MOCK_GRAPH_SUCCESS_RESULT,  # Default to success
    )

    # Mock log (Patching where used in run.py)
    # mocks["log"] = mocker.patch("reg_agent.pipelines.ingestion.run.log", autospec=True)
    # Create a MagicMock with specific methods mocked
    mock_log_instance = MagicMock()
    mock_log_instance.info = MagicMock()
    mock_log_instance.error = MagicMock()
    mock_log_instance.exception = MagicMock()
    mocks["log"] = mock_log_instance
    mocker.patch("reg_agent.pipelines.ingestion.run.log", mocks["log"])

    # Mock decorator (Keep for now, though timing is less critical with graph)
    def passthrough_decorator(task_name):
        def decorator(func):
            return func

        return decorator

    mocker.patch(
        "reg_agent.pipelines.ingestion.run.log_task_duration", passthrough_decorator
    )

    return mocks


# --- Test Cases ---


@pytest.mark.asyncio  # Add asyncio marker
async def test_run_pipeline_success(mock_dependencies):
    """Test the successful run of the refactored pipeline using the graph."""
    from reg_agent.pipelines.ingestion.run import (
        DEFAULT_DB_FILE,  # Import default for comparison if needed
        Path,  # Keep Path import for test setup
        run_ingestion_pipeline,
    )

    mock_p_constructor = mock_dependencies["Path"]
    mock_execute_graph = mock_dependencies["execute_graph"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]
    db_path_instance = mock_dependencies["db_path_instance"]

    # --- Test with specified DB file ---
    source_dir_obj = Path(MOCK_SOURCE_DIR)
    db_file_obj = Path(MOCK_DB_FILE)

    await run_ingestion_pipeline(source_dir=source_dir_obj, db_file=db_file_obj)

    # Check setup calls
    mock_p_constructor.assert_any_call(MOCK_SOURCE_DIR)
    mock_p_constructor.assert_any_call(MOCK_DB_FILE)
    source_path_instance.is_dir.assert_called_once()

    # Check graph execution call
    mock_execute_graph.assert_awaited_once_with(
        source_dir=source_path_instance, db_file=db_path_instance
    )

    # Check logging
    mock_log.info.assert_any_call(
        "Pipeline run requested",
        source_dir=str(source_path_instance),
        db_file=str(db_path_instance),
    )
    mock_log.info.assert_any_call(
        "Ingestion graph execution complete.", results=MOCK_GRAPH_SUCCESS_RESULT
    )
    mock_log.info.assert_any_call(
        "Pipeline task summaries reported by graph:", **MOCK_GRAPH_SUCCESS_RESULT
    )
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()

    # --- Reset mocks for next part of test ---
    source_path_instance.is_dir.reset_mock()
    mock_execute_graph.reset_mock()
    mock_log.reset_mock()

    # --- Test with default DB file ---
    await run_ingestion_pipeline(source_dir=source_dir_obj)

    # Check setup calls
    source_path_instance.is_dir.assert_called_once()

    # Check graph execution call uses the ACTUAL DEFAULT_DB_FILE Path object
    mock_execute_graph.assert_awaited_once_with(
        source_dir=source_path_instance,
        db_file=DEFAULT_DB_FILE,  # Use the imported default Path object directly
    )

    # Check logging uses default path string
    mock_log.info.assert_any_call(
        "Pipeline run requested",
        source_dir=str(source_path_instance),
        db_file=str(DEFAULT_DB_FILE),
    )
    mock_log.info.assert_any_call(
        "Ingestion graph execution complete.", results=MOCK_GRAPH_SUCCESS_RESULT
    )
    mock_log.info.assert_any_call(
        "Pipeline task summaries reported by graph:", **MOCK_GRAPH_SUCCESS_RESULT
    )
    mock_log.error.assert_not_called()
    mock_log.exception.assert_not_called()


@pytest.mark.asyncio  # Add asyncio marker
async def test_run_pipeline_invalid_source_dir(mock_dependencies):
    """Test pipeline halts if source directory is invalid."""
    # Import locally to avoid polluting global namespace if test is skipped
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_execute_graph = mock_dependencies["execute_graph"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    source_path_instance.is_dir.return_value = False

    await run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_log.error.assert_called_once_with(
        "Source directory does not exist or is not a directory. Halting pipeline.",
        path=str(source_path_instance),
    )
    # Ensure graph execution was NOT called
    mock_execute_graph.assert_not_awaited()


# --- Remove DB failure tests --- #
# def test_run_pipeline_get_engine_fails(mock_dependencies):
#     ...
# def test_run_pipeline_create_db_fails(mock_dependencies):
#     ...

# --- Remove old task failure tests --- #
# def test_run_pipeline_task1_fails(mock_dependencies):
#     ...
# def test_run_pipeline_task2_fails(mock_dependencies):
#     ...
# def test_run_pipeline_task3_fails(mock_dependencies):
#     ...

# --- Add new tests for graph execution outcomes --- #


@pytest.mark.asyncio
async def test_run_pipeline_graph_execution_fails(mock_dependencies):
    """Test pipeline handles exception during graph execution."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_execute_graph = mock_dependencies["execute_graph"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    # Configure the mock graph executor to raise an error
    test_exception = ValueError("Graph exploded")
    mock_execute_graph.side_effect = test_exception

    # Expect the specific exception to be raised by the pipeline function
    with pytest.raises(ValueError, match="Graph exploded"):
        await run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_execute_graph.assert_awaited_once()  # Ensure it was called
    # Check that the orchestrator caught the exception and logged it
    mock_log.exception.assert_called_once_with(
        "An unexpected error occurred during pipeline orchestration (in run.py).", error=str(test_exception)
    )
    mock_log.error.assert_not_called() # Ensure specific error logs weren't also called


@pytest.mark.asyncio
async def test_run_pipeline_graph_reports_error(mock_dependencies):
    """Test pipeline handles error dictionary returned by graph execution."""
    from reg_agent.pipelines.ingestion.run import Path, run_ingestion_pipeline

    mock_execute_graph = mock_dependencies["execute_graph"]
    mock_log = mock_dependencies["log"]
    source_path_instance = mock_dependencies["source_path_instance"]

    # Configure the mock graph executor to return an error dictionary
    error_result = {"error": "Database setup failed", "details": "Connection refused"}
    mock_execute_graph.return_value = error_result

    await run_ingestion_pipeline(source_dir=Path(MOCK_SOURCE_DIR))

    source_path_instance.is_dir.assert_called_once()
    mock_execute_graph.assert_awaited_once()
    # Check that the orchestrator logged the error reported by the graph
    mock_log.error.assert_called_once_with(
        "Pipeline execution failed within the graph.",
        error=error_result["error"],
        details=error_result["details"],
    )
    mock_log.exception.assert_not_called()
    # Ensure the final summary log was not called
    assert not any(
        call.args[0] == "Pipeline task summaries reported by graph:"
        for call in mock_log.info.call_args_list
    )
