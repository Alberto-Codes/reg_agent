# src/reg_agent/pipelines/ingestion/tasks/task_2_ocr.py

from pathlib import Path
from typing import Optional

import structlog

# from sqlalchemy.engine import Engine # Removed
# from reg_agent.core.db.connection import get_session # Replaced by UoW
from reg_agent.core.db.models import FileStatus

# from reg_agent.core.db.repositories import FileRepository # Replaced by UoW
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork  # Import UoW
from reg_agent.services.ocr_service import OcrService
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_2_ocr")
def run_task_2():  # Removed engine parameter
    """Performs OCR on records with status PENDING_PROCESS using UoW.

    Updates status to PENDING_METADATA, SKIPPED_OCR, or FAILED_OCR.

    Returns:
        Tuple[int, int, int, int]: found_count, success_count, skipped_count, error_count
    """
    records_found = 0
    success_count = 0
    skipped_count = 0
    error_count = 0

    ocr_service: Optional[OcrService] = None
    try:
        ocr_service = OcrService()
        if not ocr_service.converter:
            log.warning("OCR Service converter not initialized. Skipping Task 2.")
            return 0, 0, 0, 0

        # Use the Unit of Work context manager
        with SqlModelUnitOfWork() as uow:
            # Access the repository via uow.documents
            records_to_ocr = uow.documents.get_records_by_status(
                FileStatus.PENDING_PROCESS
            )
            records_found = len(records_to_ocr)
            log.info(f"Task 2: Found {records_found} records for OCR.")

            if not records_to_ocr:
                log.info(
                    "Task 2 Summary",
                    found=records_found,
                    success=success_count,
                    skipped=skipped_count,
                    errors=error_count,
                )
                return records_found, success_count, skipped_count, error_count

            for record in records_to_ocr:
                try:
                    extracted_markdown = ocr_service.extract_markdown_from_file(
                        Path(record.source_path)
                    )
                    # Modify record attributes directly; UoW tracks changes
                    if extracted_markdown:
                        record.extracted_text = extracted_markdown
                        record.status = FileStatus.PENDING_METADATA
                        success_count += 1
                    else:
                        record.status = FileStatus.SKIPPED_OCR
                        skipped_count += 1

                    log.debug(
                        "Processed record, staged status update",
                        record_id=record.id,
                        status=record.status,
                    )

                except Exception as e:
                    error_count += 1
                    # Modify record status; UoW tracks changes
                    record.status = FileStatus.FAILED_OCR
                    log.warning(
                        "OCR Error, staging FAILED_OCR status",
                        record_id=record.id,
                        path=record.source_path,
                        error=str(e),
                    )
            # Commit happens automatically on successful exit of 'with uow:'

    except Exception as e:
        # This catches errors initializing the UoW, OCR service, or during UoW commit
        error_count += (
            1  # Ensure error is counted if exception happens outside the loop
        )
        log.exception("Error during Task 2 processing", error=str(e))

    # Log final summary counts
    log.info(
        "Task 2 Summary",
        found=records_found,
        success=success_count,
        skipped=skipped_count,
        errors=error_count,
    )
    return records_found, success_count, skipped_count, error_count
