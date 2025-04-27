import datetime
import time
from pathlib import Path
from typing import Optional
import asyncio  # Import asyncio

import structlog
# No longer needed from sqlmodel import select

# Use create_db_and_tables and get_engine
from reg_agent.core.db.connection import (
    DEFAULT_DB_FILE,
    create_db_and_tables,
    get_engine,
    get_session,
)
# Import FileRecord and FileStatus
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository  # Import the repository

# Import services
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.services.ocr_service import OcrService

log = structlog.get_logger()


async def ingest_files(source_dir: Path, db_file: Path = DEFAULT_DB_FILE):
    """Scans a directory and ingests files into the database using a status-based approach:
    1. Create initial records (status: PENDING_PROCESS).
    2. Extract text (OCR) for records with status PENDING_PROCESS.
       - Update status to PENDING_METADATA, SKIPPED_OCR, or FAILED_OCR.
    3. Extract metadata for records with status PENDING_METADATA.
       - Update status to COMPLETED or FAILED_METADATA.

    Args:
        source_dir: The directory containing files to ingest.
        db_file: Path to the database file.
    """
    # --- Task 0: Initial Validation --- #
    if not source_dir.is_dir():
        log.error(
            "Source directory does not exist or is not a directory", path=str(source_dir)
        )
        return

    overall_start_time = time.monotonic()
    log.info(
        "Starting ingestion pipeline", source_dir=str(source_dir), db_file=str(db_file)
    )

    # --- Database Setup --- #
    try:
        engine = get_engine(db_file=db_file)
        create_db_and_tables(engine)  # Ensure tables exist
    except Exception as e:
        log.exception(
            "Failed to initialize database engine or tables. Halting ingestion.",
            error=str(e),
        )
        return

    # --- Task 1: Create Initial Records --- #
    task1_start_time = time.monotonic()
    inserted_t1 = 0
    skipped_t1 = 0
    error_t1 = 0
    log.info("Starting Task 1: Create Initial Records")
    try:
        with get_session(engine=engine) as session:
            file_repo = FileRepository(session)
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    source_path_str = str(file_path.resolve())
                    try:
                        if file_repo.exists_by_source_path(source_path_str):
                            skipped_t1 += 1
                            log.debug("Skipped existing file", path=source_path_str)
                            continue

                        file_stat = file_path.stat()
                        filename = file_path.name
                        size_bytes = file_stat.st_size
                        last_modified_ts = datetime.datetime.fromtimestamp(
                            file_stat.st_mtime, tz=datetime.timezone.utc
                        )
                        with open(file_path, "rb") as f:
                            blob_content = f.read()

                        new_record = FileRecord(
                            source_path=source_path_str,
                            filename=filename,
                            blob=blob_content,
                            extracted_text=None, # Initially None
                            meta_data=None,      # Initially None
                            size_bytes=size_bytes,
                            last_modified_ts=last_modified_ts,
                            status=FileStatus.PENDING_PROCESS # <<< Set initial status
                        )
                        file_repo.add(new_record)
                        inserted_t1 += 1

                    except OSError as e:
                        error_t1 += 1
                        log.error(
                            "OS Error processing file during Task 1",
                            file=str(file_path),
                            error=str(e),
                        )
                    except Exception as e:
                        error_t1 += 1
                        log.exception(
                            "Unexpected error processing file during Task 1",
                            file=str(file_path),
                            error=str(e),
                        )
            # Session commits automatically on exit of 'with' block if no exceptions
            session.commit() # Explicit commit after loop might be safer
            log.info("Task 1: Initial record creation complete and session committed.")
    except Exception as e:
        error_t1 += 1 # Count session/commit errors for Task 1
        log.exception("Database session/commit error during Task 1", error=str(e))

    task1_duration = time.monotonic() - task1_start_time
    log.info(
        "Task 1 Summary",
        duration_seconds=f"{task1_duration:.2f}",
        inserted=inserted_t1,
        skipped=skipped_t1,
        errors=error_t1,
    )

    # --- Task 2: Perform OCR --- #
    task2_start_time = time.monotonic()
    processed_t2 = 0
    updated_t2_success = 0 # Renamed for clarity
    updated_t2_skipped = 0
    error_t2 = 0
    log.info("Starting Task 2: Perform OCR")
    ocr_service: Optional[OcrService] = None
    try:
        ocr_service = OcrService()
        if not ocr_service.converter:
             log.warning("OCR Service converter not initialized. Skipping Task 2.")
        else:
            with get_session(engine=engine) as session:
                file_repo = FileRepository(session)
                # Fetch records needing OCR based on status
                records_to_ocr = file_repo.get_records_by_status(FileStatus.PENDING_PROCESS)
                processed_t2 = len(records_to_ocr)
                log.info(f"Found {processed_t2} records with status PENDING_PROCESS for OCR.")

                for record in records_to_ocr:
                    # Optional: Mark as processing
                    # record.status = FileStatus.PROCESSING_OCR
                    # session.add(record) # Need to add again if modifying
                    # session.commit() # Commit immediately? Or batch?
                    # log.debug("Marked record for OCR processing", record_id=record.id)

                    try:
                        extracted_markdown = ocr_service.extract_markdown_from_file(
                            Path(record.source_path)
                        )
                        if extracted_markdown:
                            record.extracted_text = extracted_markdown
                            record.status = FileStatus.PENDING_METADATA # <<< Update status
                            updated_t2_success += 1
                            log.debug(
                                "OCR successful, text extracted, status set to PENDING_METADATA",
                                record_id=record.id,
                            )
                        else:
                             record.status = FileStatus.SKIPPED_OCR # <<< Update status
                             updated_t2_skipped += 1
                             log.debug("OCR returned no text, status set to SKIPPED_OCR", record_id=record.id, path=record.source_path)
                        # Add the modified record back to the session to stage the update
                        session.add(record)

                    except Exception as e:
                        error_t2 += 1
                        record.status = FileStatus.FAILED_OCR # <<< Update status
                        session.add(record) # Stage update
                        # Log error but continue with other files
                        log.warning(
                            "Failed to extract text for record (OCR Error in Task 2), status set to FAILED_OCR",
                            record_id=record.id,
                            path=record.source_path,
                            error=str(e),
                            exc_info=False, # Keep log cleaner unless debugging needed
                        )

                # Explicitly commit session after processing all records in Task 2 batch
                session.commit()
                log.info("Task 2: OCR processing loop complete and session committed.")
    except Exception as e:
        # Errors here are likely service init or session-level problems
        error_t2 += 1 # Count general Task 2 errors (init, session, etc.)
        log.exception("Error during Task 2 setup or session management (OCR)", error=str(e))
    finally:
        # No explicit cleanup needed for OcrService currently
        pass

    task2_duration = time.monotonic() - task2_start_time
    log.info(
        "Task 2 Summary",
        duration_seconds=f"{task2_duration:.2f}",
        records_found=processed_t2,
        records_ocr_success=updated_t2_success,
        records_ocr_skipped=updated_t2_skipped,
        errors=error_t2,
    )

    # --- REMOVED time.sleep(1) --- #
    # The status field handles the transition logic now.

    # --- Task 3: Extract Metadata --- #
    task3_start_time = time.monotonic()
    processed_t3 = 0
    updated_t3_success = 0 # Renamed for clarity
    error_t3 = 0
    log.info("Starting Task 3: Extract Metadata")
    metadata_service: Optional[MetadataExtractionService] = None
    try:
        metadata_service = MetadataExtractionService()
        log.info("MetadataExtractionService initialized for Task 3.")

        with get_session(engine=engine) as session:
            file_repo = FileRepository(session)

            # --- REMOVED DIAGNOSTIC LOGGING --- #
            # The status field is now the primary way to track state.

            # Fetch records needing metadata based on status
            records_to_process = file_repo.get_records_by_status(FileStatus.PENDING_METADATA)
            processed_t3 = len(records_to_process)
            log.info(f"Found {processed_t3} records with status PENDING_METADATA.")

            for record in records_to_process:
                 # Optional: Mark as processing
                 # record.status = FileStatus.PROCESSING_METADATA
                 # session.add(record)
                 # session.commit()
                 # log.debug("Marked record for metadata processing", record_id=record.id)

                 if not record.extracted_text:
                     log.warning("Skipping metadata: Record has no extracted text despite PENDING_METADATA status", record_id=record.id)
                     record.status = FileStatus.FAILED_UNKNOWN # Or a more specific error status
                     session.add(record)
                     error_t3 += 1
                     continue

                 try:
                     extracted_meta_model = await metadata_service.extract_metadata(
                         record.extracted_text
                     )
                     if extracted_meta_model:
                         record.meta_data = extracted_meta_model.model_dump()
                         record.status = FileStatus.COMPLETED # <<< Update status
                         updated_t3_success += 1
                         session.add(record) # Stage update
                         log.debug("Metadata extracted successfully, status set to COMPLETED", record_id=record.id)
                     else:
                         record.status = FileStatus.FAILED_METADATA # <<< Update status
                         error_t3 += 1
                         session.add(record) # Stage update
                         log.warning(
                             "Metadata extraction returned None, status set to FAILED_METADATA",
                             record_id=record.id,
                             path=record.source_path,
                         )

                 except Exception as e:
                     record.status = FileStatus.FAILED_METADATA # <<< Update status
                     error_t3 += 1
                     session.add(record) # Stage update
                     log.warning(
                         "Failed to extract metadata (API Error in Task 3), status set to FAILED_METADATA",
                         record_id=record.id,
                         path=record.source_path,
                         error=str(e),
                         exc_info=False, # Keep log cleaner
                     )
            # Explicitly commit session after processing all records in Task 3 batch
            session.commit()
            log.info("Task 3: Metadata extraction processing loop complete and session committed.")

    except Exception as e:
        # Errors here are likely service init or session-level problems
        error_t3 += 1 # Count general Task 3 errors (init, session, etc.)
        log.exception("Error during Task 3 setup or session management (Metadata)", error=str(e))
    finally:
        if metadata_service and hasattr(metadata_service, "close"):
            log.info("Closing MetadataExtractionService client after Task 3.")
            try:
                await metadata_service.close()
            except Exception as close_err:
                 log.error("Error closing metadata service client", error=str(close_err))

    task3_duration = time.monotonic() - task3_start_time
    log.info(
        "Task 3 Summary",
        duration_seconds=f"{task3_duration:.2f}",
        records_found=processed_t3,
        records_metadata_success=updated_t3_success,
        errors=error_t3,
    )

    # --- Pipeline Summary --- #
    overall_duration = time.monotonic() - overall_start_time
    log.info(
        "Ingestion pipeline completed.",
        total_duration_seconds=f"{overall_duration:.2f}",
        task1_inserted=inserted_t1,
        task1_skipped=skipped_t1,
        task1_errors=error_t1,
        task2_found=processed_t2,
        task2_ocr_success=updated_t2_success,
        task2_ocr_skipped=updated_t2_skipped,
        task2_errors=error_t2,
        task3_found=processed_t3,
        task3_metadata_success=updated_t3_success,
        task3_errors=error_t3,
    )


# Example Usage (can be triggered by CLI later)
if __name__ == "__main__":  # pragma: no cover
    # Basic logging setup for direct script execution
    # Minimal structlog setup for this block
    # ... (logging setup remains the same) ...

    log.info("Running ingestion loader example")

    # Define paths
    example_db_path = Path("./db/example_ingestion_run.db")
    EXAMPLE_DIR = Path("./example_ingestion_source")

    # Clean up previous run
    if example_db_path.exists():
        example_db_path.unlink()
    EXAMPLE_DIR.mkdir(exist_ok=True)

    # Create some dummy files for the example
    (EXAMPLE_DIR / "doc1.txt").write_text("Simple text file.")
    (EXAMPLE_DIR / "doc2.pdf").write_text("Fake PDF content for testing.") # Need a PDF
    (EXAMPLE_DIR / "doc3.pdf").write_text("Another fake PDF.")
    (EXAMPLE_DIR / "doc4.log").write_text("Log file, should be skipped by OCR.")
    (EXAMPLE_DIR / "doc2.pdf").touch() # Update timestamp to test skipping logic if run twice

    # Run the ingestion pipeline asynchronously
    asyncio.run(ingest_files(source_dir=EXAMPLE_DIR, db_file=example_db_path))

    log.info("Ingestion loader example finished.")
