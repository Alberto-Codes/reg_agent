import datetime
import time
from pathlib import Path
from typing import Optional
import asyncio  # Import asyncio

import structlog

# Use create_db_and_tables and get_engine
from reg_agent.core.db.connection import (
    DEFAULT_DB_FILE,
    create_db_and_tables,
    get_engine,
    get_session,
)
from reg_agent.core.db.models import FileRecord  # Import the model
from reg_agent.core.db.repositories import FileRepository  # Import the repository

# Import services
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.services.ocr_service import OcrService

log = structlog.get_logger()


# Make the function async
async def ingest_files(source_dir: Path, db_file: Path = DEFAULT_DB_FILE):
    """Scans a directory and ingests files into the database using SQLModel and Repository.

    Args:
        source_dir: The directory containing files to ingest.
        db_file: Path to the database file (used for logging and engine initialization).
    """
    if not source_dir.is_dir():
        log.error(
            "Source directory does not exist or is not a directory",
            path=str(source_dir),
        )
        return

    log.info(
        "Starting file ingestion", source_dir=str(source_dir), db_file=str(db_file)
    )
    inserted_count = 0
    skipped_count = 0
    error_count = 0
    start_time = time.monotonic()

    # --- Initialize Services --- #
    ocr_service: Optional[OcrService] = None
    metadata_service: Optional[MetadataExtractionService] = None
    ocr_available = False
    metadata_available = False

    try:
        ocr_service = OcrService()
        ocr_available = ocr_service.converter is not None
        if not ocr_available:
            log.warning(
                "OCR Service converter not initialized. Text extraction will be skipped."
            )
    except Exception as ocr_init_err:
        log.exception("Failed to initialize OcrService", error=str(ocr_init_err))
        # Continue without OCR

    try:
        metadata_service = MetadataExtractionService()
        metadata_available = True
        log.info("MetadataExtractionService initialized successfully.")
    except Exception as meta_init_err:
        log.exception(
            "Failed to initialize MetadataExtractionService", error=str(meta_init_err)
        )
        # Continue without Metadata extraction

    # --- Database Setup --- #
    engine = None  # Ensure engine is defined for finally block
    try:
        engine = get_engine(db_file=db_file)
        create_db_and_tables(engine)  # Ensure tables exist using the correct engine
    except Exception as e:
        log.exception(
            "Failed to initialize database engine or tables. Halting ingestion.",
            error=str(e),
        )
        # Ensure metadata service client is closed if initialized
        if metadata_service and hasattr(metadata_service, "close"):
            await metadata_service.close()
        return  # Stop ingestion if DB setup fails

    # --- Main Processing Loop --- #
    try:
        with get_session(engine=engine) as session:
            log.debug("Database session obtained for ingestion.")
            file_repo = FileRepository(session)  # Instantiate repository with session

            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    source_path_str = str(file_path.resolve())  # Use absolute path
                    extracted_markdown: Optional[str] = None
                    extracted_meta_dict: Optional[dict] = (
                        None  # Variable for metadata dict
                    )

                    try:
                        # 1. Check if record exists using the repository
                        if file_repo.exists_by_source_path(source_path_str):
                            skipped_count += 1
                            log.debug("Skipped existing file", path=source_path_str)
                            continue  # Skip to the next file

                        # 2. Get File Metadata
                        file_stat = file_path.stat()
                        filename = file_path.name
                        size_bytes = file_stat.st_size
                        last_modified_ts = datetime.datetime.fromtimestamp(
                            file_stat.st_mtime, tz=datetime.timezone.utc
                        )

                        # 3. Read Blob
                        with open(file_path, "rb") as f:
                            blob_content = f.read()

                        # 4. Attempt Text Extraction (OCR)
                        if ocr_available and ocr_service:
                            try:
                                extracted_markdown = (
                                    ocr_service.extract_markdown_from_file(file_path)
                                )
                            except Exception as ocr_err:
                                log.warning(
                                    "Failed to extract text from file (OCR)",
                                    file=source_path_str,
                                    error=str(ocr_err),
                                    exc_info=False,
                                )

                        # 5. Attempt Metadata Extraction
                        if (
                            metadata_available
                            and metadata_service
                            and extracted_markdown
                        ):
                            log.debug(
                                "Attempting metadata extraction", file=source_path_str
                            )
                            try:
                                # Call the async metadata service
                                extracted_meta_model = (
                                    await metadata_service.extract_metadata(
                                        extracted_markdown
                                    )
                                )
                                if extracted_meta_model:
                                    # Convert Pydantic model to dict
                                    extracted_meta_dict = (
                                        extracted_meta_model.model_dump()
                                    )
                                    log.info(
                                        "Metadata extracted successfully",
                                        file=source_path_str,
                                    )
                                else:
                                    log.warning(
                                        "Metadata extraction returned None",
                                        file=source_path_str,
                                    )
                            except Exception as meta_err:
                                log.warning(
                                    "Failed to extract metadata from text",
                                    file=source_path_str,
                                    error=str(meta_err),
                                    exc_info=False,
                                )

                        # 6. Create FileRecord Model instance
                        new_record = FileRecord(
                            source_path=source_path_str,
                            filename=filename,
                            blob=blob_content,
                            extracted_text=extracted_markdown,
                            meta_data=extracted_meta_dict,  # Assign metadata dict
                            size_bytes=size_bytes,
                            last_modified_ts=last_modified_ts,
                        )

                        # 7. Add record to session via repository
                        file_repo.add(new_record)  # Repository adds to session
                        inserted_count += 1

                    except OSError as e:
                        error_count += 1
                        log.error(
                            "OS Error processing file",
                            file=str(file_path),
                            error=str(e),
                        )
                    except Exception as e:
                        error_count += 1
                        log.exception(
                            "Unexpected error processing file",
                            file=str(file_path),
                            error=str(e),
                        )

            log.debug("Session commit (or rollback) handled by context manager.")

    except Exception as e:
        error_count += 1
        log.exception("Database session/commit error during ingestion", error=str(e))
    finally:
        # --- Service Cleanup --- #
        if metadata_service and hasattr(metadata_service, "close"):
            log.info("Closing MetadataExtractionService client.")
            await metadata_service.close()
        # No explicit close needed for OcrService currently

    end_time = time.monotonic()
    duration = end_time - start_time
    log.info(
        "File ingestion completed",
        duration_seconds=f"{duration:.2f}",
        inserted=inserted_count,
        skipped=skipped_count,
        errors=error_count,
        total_processed=inserted_count + skipped_count + error_count,
        source_dir=str(source_dir),
    )


# Example Usage (can be triggered by CLI later)
if __name__ == "__main__":  # pragma: no cover
    log.info("Running ingestion loader example")

    # Define paths
    example_db_path = Path("./db/example_ingestion_run.db")
    EXAMPLE_DIR = Path("./example_ingestion_source")

    # Clean up previous run
    if example_db_path.exists():
        example_db_path.unlink()
    # Clean up and recreate example source dir (optional)
    # import shutil
    # if EXAMPLE_DIR.exists():
    #     shutil.rmtree(EXAMPLE_DIR)
    EXAMPLE_DIR.mkdir(exist_ok=True)

    # Database initialization is handled within ingest_files now
    # by calling get_engine and create_db_and_tables

    log.info("Setting up example files...", source_dir=str(EXAMPLE_DIR))
    # --- Rest of the example setup ---
    dummy_file = EXAMPLE_DIR / "my_test_file.txt"
    dummy_file.write_text("This is the content of the test file.\n")

    sub_dir = EXAMPLE_DIR / "subdir"
    sub_dir.mkdir(exist_ok=True)
    dummy_file_2 = sub_dir / "another_file.log"
    dummy_file_2.write_text("Log line 1\nLog line 2")

    # Assume a dummy PDF exists at EXAMPLE_DIR / "dummy.pdf" for a full test.
    # You would need to place one there manually or generate it.
    # Example dummy PDF creation (requires reportlab):
    try:
        from reportlab.lib.pagesizes import letter  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore

        dummy_pdf_path = EXAMPLE_DIR / "dummy.pdf"
        c = canvas.Canvas(str(dummy_pdf_path), pagesize=letter)
        c.drawString(100, 750, "This is a dummy PDF document.")
        c.save()
        log.info("Created dummy PDF.", path=str(dummy_pdf_path))
    except ImportError:
        log.warning("reportlab not installed. Cannot create dummy PDF for example run.")
    except Exception as pdf_err:
        log.error("Failed to create dummy PDF.", error=str(pdf_err))

    log.info(
        "Ingesting example files", source=str(EXAMPLE_DIR), db=str(example_db_path)
    )
    # Pass the specific DB path to ensure the correct engine is used
    asyncio.run(ingest_files(EXAMPLE_DIR, db_file=example_db_path))

    log.info("Checking database content after example ingestion...")
    try:
        # Use the session to query, getting engine with the correct path
        engine = get_engine(db_file=example_db_path)
        with get_session(engine=engine) as session:  # Pass the specific engine
            repo = FileRepository(session)
            # Example: Fetch all records
            from sqlmodel import select

            statement = select(FileRecord)
            results = session.exec(statement).all()
            log.info("Files found in DB", count=len(results))
            for record in results:
                log.info(
                    "Record details",
                    path=record.source_path,
                    text_present=record.extracted_text is not None,
                    text_len=len(record.extracted_text) if record.extracted_text else 0,
                )

    except Exception:
        log.exception("Error checking example DB content")

    # --- Cleanup ---
    # print("Cleanup: Example directory and DB file left for inspection.")
    # print(f"DB at: {example_db_path.resolve()}")
    # print(f"Source dir at: {EXAMPLE_DIR.resolve()}")
