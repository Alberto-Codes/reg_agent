# src/reg_agent/pipelines/ingestion/tasks/task_3_metadata.py

import asyncio
from typing import Optional

import structlog

# from sqlalchemy.engine import Engine # Removed
# from reg_agent.core.db.connection import get_session # Replaced by UoW
from reg_agent.core.db.models import FileStatus

# from reg_agent.core.db.repositories import FileRepository # Replaced by UoW
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork  # Import UoW
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_3_metadata")
async def run_task_3():  # Removed engine parameter
    """Extracts metadata for records with status PENDING_METADATA using UoW.

    Initializes MetadataExtractionService once and processes records within a single UoW.
    Uses synchronous database operations tracked by UoW within the async function.

    Returns:
        Tuple[int, int, int]: found_count, success_count, error_count
    """
    records_found = 0
    success_count = 0
    error_count = 0

    # Initialize service once outside the UoW and loop
    metadata_service: Optional[MetadataExtractionService] = None
    try:
        metadata_service = MetadataExtractionService()
        log.info("MetadataExtractionService initialized for Task 3.")
    except Exception as service_init_err:
        log.exception(
            "Failed to initialize MetadataExtractionService",
            error=str(service_init_err),
        )
        # Cannot proceed without the service
        return 0, 0, 1  # Return 1 error for service init failure

    try:
        # Wrap entire fetch and process logic in a single UoW
        with SqlModelUnitOfWork() as uow:
            # Fetch records inside the UoW - Include FAILED_METADATA for retry
            statuses_to_process = [
                FileStatus.PENDING_METADATA,
                FileStatus.FAILED_METADATA,
            ]
            log.info("Querying for records with statuses", statuses=statuses_to_process)
            records_to_process = uow.documents.get_records_by_status(
                statuses_to_process  # Pass list as positional argument
            )
            records_found = len(records_to_process)
            log.info(f"Task 3: Found {records_found} records for metadata extraction.")

            if not records_to_process:
                # Still log summary, even if no records found
                log.info(
                    "Task 3 Summary",
                    found=records_found,
                    success=success_count,
                    errors=error_count,
                )
                return records_found, success_count, error_count  # Exit early

            for record in records_to_process:
                await asyncio.sleep(2)  # Keep the delay

                if not record.extracted_text:
                    log.warning(
                        "Skipping metadata: Record has no extracted text",
                        record_id=record.id,
                    )
                    # Update status directly; UoW tracks the change
                    record.status = FileStatus.FAILED_UNKNOWN
                    log.info("Staging status to FAILED_UNKNOWN", record_id=record.id)
                    error_count += 1
                    continue  # Move to the next record

                # --- Call Metadata Service --- #
                try:
                    extracted_meta_model = await metadata_service.extract_metadata(
                        record.extracted_text
                    )

                    # --- Update record based on result; UoW tracks changes --- #
                    if extracted_meta_model:
                        record.status = FileStatus.COMPLETED
                        record.meta_data = extracted_meta_model.model_dump()
                        log.debug(
                            "Staging COMPLETED status and metadata", record_id=record.id
                        )
                        success_count += 1
                    else:
                        record.status = FileStatus.FAILED_METADATA
                        log.debug(
                            "Staging FAILED_METADATA status (API returned None)",
                            record_id=record.id,
                        )
                        error_count += 1
                    # No explicit session.add(record) needed here
                    # --- End Update --- #

                except Exception as e:
                    # Handle API/Service errors during extraction for *this* record
                    log.warning(
                        "Metadata extraction API/Service error for record",
                        record_id=record.id,
                        path=record.source_path,
                        error=str(e),
                        exc_info=False,
                    )
                    # Update status directly; UoW tracks the change
                    record.status = FileStatus.FAILED_METADATA
                    log.debug(
                        "Staging FAILED_METADATA status after API error",
                        record_id=record.id,
                    )
                    error_count += 1
                    # No explicit session.add(record) needed here

            # Commit for all processed records happens automatically on successful exit of 'with uow:'

    except Exception as e:
        # This catches errors initializing the UoW or during the UoW commit/rollback
        log.exception("Error during Task 3 Unit of Work execution", error=str(e))
        # We don't know how many records were intended, return initial counts + 1 general error
        # Note: Individual record errors inside the loop are already counted.
        # This error count might be slightly off if the commit fails after some successes.
        # A more robust approach might involve tracking IDs intended vs committed.
        error_count += 1  # Add error for the UoW context issue

    log.info(
        "Task 3 Summary",
        found=records_found,
        success=success_count,
        errors=error_count,
    )
    return records_found, success_count, error_count
