# src/reg_agent/pipelines/ingestion/tasks/task_3_metadata.py

import asyncio
import uuid  # Import uuid
from typing import List, Optional, TypedDict, Dict, Any

import structlog

# from sqlalchemy.engine import Engine # Removed
# from reg_agent.core.db.connection import get_session # Replaced by UoW
from reg_agent.core.db.models import FileStatus

# from reg_agent.core.db.repositories import FileRepository # Replaced by UoW
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork  # Import UoW
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


# Define a type for the error details dictionary
class Task3ErrorDetail(TypedDict):
    record_id: str
    filename: str
    status: FileStatus
    error_message: str


# Define a type for the return dictionary
class Task3Result(TypedDict):
    found: int
    success: int
    errors: int
    error_details: List[Task3ErrorDetail]


@log_task_duration("task_3_metadata")
async def run_task_3() -> Task3Result:  # Update return type annotation
    """Extracts metadata for records with status PENDING_METADATA using UoW.

    Initializes MetadataExtractionService once and processes records within a single UoW.
    Uses synchronous database operations tracked by UoW within the async function.
    Ensures MetadataExtractionService is closed if initialized.
    Collects details about failed records.

    Returns:
        Task3Result: A dictionary containing counts and a list of error details.
    """
    records_found = 0
    success_count = 0
    error_count = 0
    error_details: List[Task3ErrorDetail] = []  # Initialize error details list
    metadata_service: Optional[MetadataExtractionService] = (
        None  # Initialize outside try
    )
    final_result: Task3Result = {
        "found": 0, "success": 0, "errors": 0, "error_details": []
    } # Initialize default return

    try:
        # --- Initialize Service --- #
        try:
            metadata_service = MetadataExtractionService()
            log.info("MetadataExtractionService initialized for Task 3.")
        except Exception as service_init_err:
            err_msg = f"Failed to initialize MetadataExtractionService: {service_init_err}"
            log.exception(err_msg)
            # Cannot proceed without the service
            final_result["errors"] = 1
            final_result["error_details"].append({
                "record_id": "N/A",
                "filename": "N/A",
                "status": FileStatus.FAILED_METADATA, # Use this for service init failure
                "error_message": err_msg
            })
            return final_result

        # --- Process Records using UoW --- #
        try:
            # Wrap entire fetch and process logic in a single UoW
            with SqlModelUnitOfWork() as uow:
                # Fetch records inside the UoW - Include FAILED_METADATA for retry
                statuses_to_process = [
                    FileStatus.PENDING_METADATA,
                    FileStatus.FAILED_METADATA,
                    FileStatus.FAILED_LLM_OUTPUT, # Also retry LLM output failures
                ]
                log.info(
                    "Querying for records with statuses", statuses=statuses_to_process
                )
                records_to_process = uow.documents.get_records_by_status(
                    statuses_to_process  # Pass list as positional argument
                )
                records_found = len(records_to_process)
                log.info(
                    f"Task 3: Found {records_found} records for metadata extraction."
                )

                if not records_to_process:
                    pass  # Let summary log outside the loop handle this
                else:
                    for record in records_to_process:
                        # Ensure record.id is a UUID before proceeding
                        if not isinstance(record.id, uuid.UUID):
                           log.error("Invalid record ID type found", record_id=record.id)
                           # Handle this case, maybe skip or assign a default error
                           error_count += 1
                           error_details.append({
                               "record_id": str(record.id) if record.id else "Unknown ID",
                               "filename": record.filename if record.filename else "Unknown Filename",
                               "status": FileStatus.FAILED_UNKNOWN,
                               "error_message": "Invalid record ID type encountered"
                           })
                           continue # Skip this record

                        await asyncio.sleep(2)  # Keep the delay

                        if not record.extracted_text:
                            err_msg = "Skipping metadata: Record has no extracted text"
                            log.warning(err_msg, record_id=record.id)
                            record.status = FileStatus.FAILED_UNKNOWN
                            log.info(
                                "Staging status to FAILED_UNKNOWN", record_id=record.id
                            )
                            error_count += 1
                            error_details.append({ # Add error detail
                                "record_id": str(record.id),
                                "filename": record.filename,
                                "status": FileStatus.FAILED_UNKNOWN,
                                "error_message": err_msg
                            })
                            continue

                        # --- Call Metadata Service with Retry Logic --- #
                        extracted_meta_model = None  # Initialize before retry loop
                        service_call_succeeded = False
                        final_exception_message = "No error occurred" # Store last exception message

                        for attempt in range(MAX_RETRIES):
                            try:
                                # Check service exists before calling (should always here)
                                if not metadata_service:
                                    raise RuntimeError(
                                        "Metadata service not initialized unexpectedly"
                                    )

                                extracted_meta_model = (
                                    await metadata_service.extract_metadata(
                                        record.extracted_text
                                    )
                                )
                                service_call_succeeded = True  # Mark success
                                break  # Exit retry loop on success

                            except Exception as e:
                                final_exception_message = str(e) # Update last error
                                log.warning(
                                    "Metadata extraction attempt failed",
                                    record_id=record.id,
                                    attempt=attempt + 1,
                                    max_retries=MAX_RETRIES,
                                    error=final_exception_message,
                                    exc_info=True,  # Keep traceback for warnings during retry
                                )
                                if attempt < MAX_RETRIES - 1:
                                    log.info(
                                        f"Waiting {RETRY_DELAY_SECONDS}s before next retry...",
                                        record_id=record.id,
                                        attempt=attempt + 1,
                                    )
                                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                                else:
                                    # Last attempt failed
                                    log.error(
                                        "Metadata extraction failed after all retries",
                                        record_id=record.id,
                                        path=record.source_path,
                                        error=final_exception_message,  # Final error message
                                        exc_info=True,  # Ensure traceback on final failure
                                    )
                                    # service_call_succeeded remains False

                        # --- Update record based on final result after retries --- #
                        if service_call_succeeded:
                            if extracted_meta_model:
                                record.status = FileStatus.COMPLETED
                                record.meta_data = extracted_meta_model.model_dump()
                                log.debug(
                                    "Staging COMPLETED status and metadata",
                                    record_id=record.id,
                                )
                                success_count += 1
                            else:
                                # Set specific status if API worked but output was None/invalid
                                record.status = FileStatus.FAILED_LLM_OUTPUT
                                err_msg = "LLM output invalid/unparsable (API returned None/invalid)"
                                log.debug(
                                    f"Staging {FileStatus.FAILED_LLM_OUTPUT} status ({err_msg})",
                                    record_id=record.id,
                                )
                                error_count += 1
                                error_details.append({ # Add error detail
                                    "record_id": str(record.id),
                                    "filename": record.filename,
                                    "status": FileStatus.FAILED_LLM_OUTPUT,
                                    "error_message": err_msg
                                })
                        else:
                            # Service call failed after all retries
                            record.status = FileStatus.FAILED_METADATA
                            err_msg = f"API/Service error after retries: {final_exception_message}"
                            log.debug(
                                f"Staging {FileStatus.FAILED_METADATA} status ({err_msg})",
                                record_id=record.id,
                            )
                            error_count += 1
                            error_details.append({ # Add error detail
                                "record_id": str(record.id),
                                "filename": record.filename,
                                "status": FileStatus.FAILED_METADATA,
                                "error_message": err_msg
                            })

        except Exception as e:
            # Catches errors initializing UoW or during UoW commit/rollback
            err_msg = f"Error during Task 3 Unit of Work execution: {e}"
            log.exception(err_msg)
            # Indicate a general UoW error - might affect multiple records
            error_count += 1 # Count this as one major error for now
            error_details.append({
                "record_id": "N/A",
                "filename": "N/A",
                "status": FileStatus.FAILED_UNKNOWN,
                "error_message": err_msg
            })


    finally:
        # --- Ensure Service Cleanup --- #
        if metadata_service and hasattr(metadata_service, "close"):
            try:
                log.info("Attempting to close MetadataExtractionService client.")
                await metadata_service.close()
                log.info("MetadataExtractionService client closed successfully.")
            except Exception as close_err:
                log.warning(
                    "Error closing MetadataExtractionService client",
                    error=str(close_err),
                )

        # --- Update final result structure --- #
        final_result["found"] = records_found
        final_result["success"] = success_count
        final_result["errors"] = error_count
        final_result["error_details"] = error_details

        # --- Log Final Summary --- #
        # Explicitly type the log data dictionary
        summary_log_data: Dict[str, Any] = {
            "found": records_found,
            "success": success_count,
            "errors": error_count,
        }
        # Only include error_details in log if there are errors
        if error_details:
           summary_log_data["error_details"] = error_details

        log.info("Task 3 Summary", **summary_log_data)

    return final_result
