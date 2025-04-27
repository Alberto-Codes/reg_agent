# src/reg_agent/pipelines/ingestion/run.py

import asyncio  # Need asyncio to run Task 3
from pathlib import Path

import structlog

# Use sync Engine
from sqlalchemy.engine import Engine

# --- Core Imports ---
from reg_agent.core.db.connection import (
    DEFAULT_DB_FILE,
    create_db_and_tables,
    get_engine,
)

# --- Service Imports ---
# from reg_agent.services.metadata_service import MetadataExtractionService
# from reg_agent.services.ocr_service import OcrService # Not injecting OCR service for now
# --- Task Imports ---
from reg_agent.pipelines.ingestion.tasks.task_1_create_records import run_task_1
from reg_agent.pipelines.ingestion.tasks.task_2_ocr import run_task_2
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import run_task_3

# --- Utility Imports ---
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("ingestion_pipeline")
def run_ingestion_pipeline(source_dir: Path, db_file: Path = DEFAULT_DB_FILE):
    """Orchestrates the ingestion pipeline by running tasks sequentially (Synchronous Version).

    1. Creates initial records for new files.
    2. Performs OCR on pending records.
    3. Extracts metadata using an LLM for records with text.

    Args:
        source_dir: The directory containing files to ingest.
        db_file: Path to the database file.
    """
    log.info("Pipeline run details", source_dir=str(source_dir), db_file=str(db_file))

    # --- Initial Validation --- #
    if not source_dir.is_dir():
        log.error(
            "Source directory does not exist or is not a directory. Halting pipeline.",
            path=str(source_dir),
        )
        return

    # --- Database Setup --- #
    engine: Engine | None = None
    try:
        engine = get_engine(db_file=db_file)
        # Ensure tables exist - moved this here from old loader Task 0
        create_db_and_tables(engine)
    except Exception as e:
        log.exception(
            "Failed to initialize database engine or tables. Halting pipeline.",
            error=str(e),
        )
        return  # Stop if DB setup fails

    # --- Remove Service Initialization from Orchestrator --- #
    # metadata_service: MetadataExtractionService | None = None # Removed

    try:
        # --- Run Tasks Sequentially (Sync for T1, T2) --- #

        # Task 1: Create Records (Sync)
        t1_inserted, t1_skipped, t1_errors = run_task_1(source_dir)
        log.info(
            "Task 1 (Create Records) summary",
            inserted=t1_inserted,
            skipped=t1_skipped,
            errors=t1_errors,
        )
        # Decide if pipeline should continue based on Task 1 errors?
        # For now, continue even if some file reads failed.

        # Task 2: OCR (Sync)
        t2_found, t2_success, t2_skipped, t2_errors = run_task_2()
        log.info(
            "Task 2 (OCR) summary",
            found=t2_found,
            success=t2_success,
            skipped=t2_skipped,
            errors=t2_errors,
        )
        # Continue even if OCR failed for some files.

        # Task 3: Metadata Extraction (Async Call within Sync Orchestrator)
        # Run the async task 3 using asyncio.run() - It now handles its own service
        log.info("Starting Task 3 (Metadata) asynchronously...")
        t3_found, t3_success, t3_errors = asyncio.run(run_task_3())
        log.info(
            "Task 3 (Metadata) summary",
            found=t3_found,
            success=t3_success,
            errors=t3_errors,
        )

        # --- Pipeline Summary (Optional) --- #
        # The decorator already logs total time.
        # We could log combined stats here if needed.
        log.info(
            "Pipeline task summaries complete.",
            task1_results=(t1_inserted, t1_skipped, t1_errors),
            task2_results=(t2_found, t2_success, t2_skipped, t2_errors),
            task3_results=(t3_found, t3_success, t3_errors),
        )

    except Exception as e:
        log.exception(
            "An unexpected error occurred during pipeline execution.", error=str(e)
        )
        # This catches errors in service init or task execution not caught internally

    # --- Remove Service Cleanup from Orchestrator --- #
    # finally:
    #     if metadata_service:
    #        asyncio.run(metadata_service.close()) # Removed

    # Decorator handles the final "Finished task: ingestion_pipeline" log
