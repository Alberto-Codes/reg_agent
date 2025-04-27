# src/reg_agent/pipelines/ingestion/tasks/task_2_ocr.py

from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy.engine import Engine

from reg_agent.core.db.connection import get_session
from reg_agent.core.db.models import FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.services.ocr_service import OcrService
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_2_ocr")
def run_task_2(engine: Engine):
    """Performs OCR on records with status PENDING_PROCESS (Synchronous Version).

    Updates status to PENDING_METADATA, SKIPPED_OCR, or FAILED_OCR.

    Args:
        engine: The SQLAlchemy SyncEngine for database interaction.

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

        with get_session(engine=engine) as session:
            file_repo = FileRepository(session)
            records_to_ocr = file_repo.get_records_by_status(FileStatus.PENDING_PROCESS)
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
                    record_modified = False
                    if extracted_markdown:
                        record.extracted_text = extracted_markdown
                        record.status = FileStatus.PENDING_METADATA
                        success_count += 1
                        record_modified = True
                    else:
                        record.status = FileStatus.SKIPPED_OCR
                        skipped_count += 1
                        record_modified = True

                    if record_modified:
                        session.add(record)
                        log.debug(
                            "Staged record update",
                            record_id=record.id,
                            status=record.status,
                        )

                except Exception as e:
                    error_count += 1
                    record.status = FileStatus.FAILED_OCR
                    session.add(record)
                    log.warning(
                        "OCR Error, staging FAILED_OCR status",
                        record_id=record.id,
                        path=record.source_path,
                        error=str(e),
                    )

            # Commit happens automatically via sync context manager exit

    except Exception as e:
        error_count += 1
        log.exception("Error during Task 2 session or execution", error=str(e))

    # Log final summary counts
    log.info(
        "Task 2 Summary",
        found=records_found,
        success=success_count,
        skipped=skipped_count,
        errors=error_count,
    )
    return records_found, success_count, skipped_count, error_count
