# src/reg_agent/pipelines/ingestion/run.py

from pathlib import Path
from typing import Any, Dict

import structlog

# --- Core Imports ---
from reg_agent.core.db.connection import DEFAULT_DB_FILE

# --- Task Imports ---
# from reg_agent.pipelines.ingestion.tasks.task_1_create_records import run_task_1
# from reg_agent.pipelines.ingestion.tasks.task_2_ocr import run_task_2
# from reg_agent.pipelines.ingestion.tasks.task_3_metadata import run_task_3
# --- Graph Import ---
from reg_agent.pipelines.ingestion.graph import execute_ingestion_graph

# --- Utility Imports ---
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("ingestion_pipeline")
async def run_ingestion_pipeline(source_dir: Path, db_file: Path = DEFAULT_DB_FILE):
    """Orchestrates the ingestion pipeline by executing the pydantic-graph definition.

    The graph handles:
    1. Database setup.
    2. Creating initial records for new files.
    3. Performing OCR on pending records.
    4. Extracting metadata using an LLM for records with text.
    5. Aggregating results.

    Args:
        source_dir: The directory containing files to ingest.
        db_file: Path to the database file.
    """
    log.info("Pipeline run requested", source_dir=str(source_dir), db_file=str(db_file))

    # --- Initial Validation --- # (Keep this basic check here)
    if not source_dir.is_dir():
        log.error(
            "Source directory does not exist or is not a directory. Halting pipeline.",
            path=str(source_dir),
        )
        return

    try:
        # --- Execute the Graph ---
        # log.info("DEBUG: Attempting graph execution...")
        # Call ASYNC graph execution function WITH await
        results: Dict[str, Any] = await execute_ingestion_graph(
            source_dir=source_dir, db_file=db_file
        )
        # log.info("DEBUG: Graph execution attempt finished.")
        log.info("Ingestion graph execution complete.", results=results)

        # Check results for errors reported by the graph executor
        if results.get("error"):
            log.error(
                "Pipeline execution failed within the graph.",
                error=results.get("error"),
                details=results.get("details"),
            )
        else:
            # Log the detailed results from the aggregate_results node
            log.info("Pipeline task summaries reported by graph:", **results)

    except Exception as e:
        # Catch errors that might occur *outside* the graph execution call itself
        # (e.g., during the initial source_dir check or if execute_ingestion_graph raises unexpectedly)
        log.exception(
            "An unexpected error occurred during pipeline orchestration (in run.py).",
            error=str(e),
        )
        # print(f"ERROR in run_ingestion_pipeline: {e!r}")
        raise

    # Decorator handles the final "Finished task: ingestion_pipeline" log
    # No finally block needed here as graph execution handles its own resources (like DB setup error)
    # and task-specific resources (like LLM client in task 3) are managed within the tasks.
