# src/reg_agent/pipelines/ingestion/tasks/task_3_metadata.py

import asyncio
from typing import Optional

import structlog
from sqlalchemy.engine import Engine

from reg_agent.core.db.connection import get_session
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_3_metadata")
async def run_task_3(engine: Engine):
    """Extracts metadata for records with status PENDING_METADATA.

    Initializes MetadataExtractionService internally per record.
    Uses synchronous database operations within the async function.

    Args:
        engine: The SQLAlchemy synchronous Engine for database interaction.

    Returns:
        Tuple[int, int, int]: found_count, success_count, error_count
    """
    records_found = 0
    success_count = 0
    error_count = 0
    records_processed_ids = set()

    # Initial fetch needs its own session block
    records_data = []  # Initialize records_data
    try:
        with get_session(engine=engine) as session:
            file_repo = FileRepository(session)
            records_to_process = file_repo.get_records_by_status(
                FileStatus.PENDING_METADATA
            )
            records_found = len(records_to_process)
            records_data = [
                (r.id, r.source_path, r.extracted_text) for r in records_to_process
            ]
        log.info(f"Task 3: Found {records_found} records for metadata extraction.")
    except Exception as e:
        log.exception("Error fetching records for Task 3", error=str(e))
        return 0, 0, 0

    if not records_data:
        log.info(
            "Task 3 Summary",
            found=records_found,
            success=success_count,
            errors=error_count,
        )
        return records_found, success_count, error_count

    for record_id, source_path, extracted_text in records_data:
        if record_id in records_processed_ids:
            continue

        await asyncio.sleep(2)  # Delay between API calls

        if not extracted_text:
            log.warning(
                "Skipping metadata: Record has no extracted text",
                record_id=record_id,
            )
            try:
                with get_session(engine=engine) as update_session:
                    # Fetch the specific record to update
                    record = update_session.get(FileRecord, record_id)
                    if record:
                        record.status = FileStatus.FAILED_UNKNOWN
                        update_session.add(record)
                        # Commit happens on session exit
                        log.info(
                            "Updating status to FAILED_UNKNOWN", record_id=record_id
                        )
                    else:
                        log.error(
                            "Could not find record to update status to FAILED_UNKNOWN",
                            record_id=record_id,
                        )
            except Exception as commit_err:
                log.error(
                    "Failed session/commit for FAILED_UNKNOWN status",
                    record_id=record_id,
                    error=str(commit_err),
                )
            error_count += 1
            records_processed_ids.add(record_id)
            continue

        # --- Service Init & API Call per Record --- #
        metadata_service: Optional[MetadataExtractionService] = None
        try:
            # Initialize service inside the loop
            metadata_service = MetadataExtractionService()
            log.info(
                "MetadataExtractionService initialized for record", record_id=record_id
            )

            extracted_meta_model = await metadata_service.extract_metadata(
                extracted_text
            )

            # --- Sync DB Update --- #
            update_status = None
            update_metadata = None
            commit_log_msg = ""

            if extracted_meta_model:
                update_status = FileStatus.COMPLETED
                update_metadata = extracted_meta_model.model_dump()
                commit_log_msg = "Committing COMPLETED status and metadata"
                success_count += 1
            else:
                update_status = FileStatus.FAILED_METADATA
                commit_log_msg = "Committing FAILED_METADATA status (API returned None)"
                error_count += 1

            try:
                with get_session(engine=engine) as update_session:
                    record = update_session.get(FileRecord, record_id)
                    if record:
                        log.debug(commit_log_msg, record_id=record_id)
                        record.status = update_status
                        if update_metadata:
                            record.meta_data = update_metadata
                        update_session.add(record)
                        # Commit happens on session exit
                    else:
                        log.error(
                            "Could not find record to update metadata status",
                            record_id=record_id,
                            target_status=update_status,
                        )
                        # Adjust counts if record vanished?
                        if update_status == FileStatus.COMPLETED:
                            success_count -= 1
                        else:
                            error_count -= 1  # Decrement if we counted it
                        error_count += 1  # Add error for missing record
                        continue  # Skip to next record

            except Exception as commit_err:
                log.error(
                    "Failed session/commit updating metadata status",
                    record_id=record_id,
                    error=str(commit_err),
                )
                # Adjust counts as commit failed
                if update_status == FileStatus.COMPLETED:
                    success_count -= 1
                else:
                    error_count -= 1  # Decrement if we counted it
                error_count += 1  # Add error for the commit failure
            # --- End Sync DB Update --- #

        except Exception as e:
            # Handle API/Service errors
            log.warning(
                "Metadata extraction API/Service error for record",
                record_id=record_id,
                path=source_path,
                error=str(e),
                exc_info=False,
            )
            # --- Sync DB Update for API Error --- #
            try:
                with get_session(engine=engine) as update_session:
                    record = update_session.get(FileRecord, record_id)
                    if record:
                        log.debug(
                            "Committing FAILED_METADATA status after API error",
                            record_id=record_id,
                        )
                        record.status = FileStatus.FAILED_METADATA
                        update_session.add(record)
                        # Commit happens on session exit
                    else:
                        log.error(
                            "Could not find record to update status after API error",
                            record_id=record_id,
                        )
            except Exception as commit_err:
                log.error(
                    "Failed session/commit updating FAILED_METADATA status after API error",
                    record_id=record_id,
                    error=str(commit_err),
                )
            error_count += 1
            # --- End Sync DB Update for API Error --- #

        finally:
            # --- Close Service Instance --- #
            if metadata_service:
                try:
                    await metadata_service.close()
                    log.info(
                        "MetadataExtractionService closed for record",
                        record_id=record_id,
                    )
                except Exception as close_err:
                    log.error(
                        "Failed to close service for record",
                        record_id=record_id,
                        error=str(close_err),
                    )
            records_processed_ids.add(record_id)

    # Log final summary counts
    log.info(
        "Task 3 Summary", found=records_found, success=success_count, errors=error_count
    )
    return records_found, success_count, error_count
