# src/reg_agent/pipelines/ingestion/tasks/task_1_create_records.py

import datetime
from pathlib import Path

import structlog

# from sqlalchemy.engine import Engine # No longer needed as arg
# from reg_agent.core.db.connection import get_session # Replaced by UoW
from reg_agent.core.db.models import FileRecord, FileStatus

# from reg_agent.core.db.repositories import FileRepository # Replaced by UoW
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork  # Import UoW
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_1_create_records")
def run_task_1(source_dir: Path):  # Removed engine parameter
    """Scans the source directory and creates initial FileRecord entries
    in the database for new files found using Unit of Work.

    Args:
        source_dir: The directory containing files to ingest.

    Returns:
        Tuple[int, int, int]: inserted_count, skipped_count, error_count
    """
    inserted_count = 0
    skipped_count = 0
    error_count = 0

    try:
        # Use the Unit of Work context manager
        with SqlModelUnitOfWork() as uow:
            # Access the repository via uow.documents
            for file_path in source_dir.rglob("*"):
                try:
                    if file_path.is_file():
                        source_path_str = str(file_path.resolve())

                        # Use repository from UoW
                        if uow.documents.exists_by_source_path(source_path_str):
                            skipped_count += 1
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
                            extracted_text=None,
                            meta_data=None,
                            size_bytes=size_bytes,
                            last_modified_ts=last_modified_ts,
                            status=FileStatus.PENDING_PROCESS,
                        )

                        # Use repository add method from UoW
                        uow.documents.add(new_record)
                        inserted_count += 1
                        log.debug(
                            "Staged new FileRecord (pending UoW commit)",
                            path=source_path_str,
                            record_id=new_record.id,
                        )

                except OSError as e:
                    error_count += 1
                    log.error(
                        "OS Error processing path during Task 1",
                        path=str(file_path),
                        error=str(e),
                    )
                except Exception as e:
                    error_count += 1
                    log.exception(
                        "Unexpected error processing path during Task 1",
                        path=str(file_path),
                        error=str(e),
                    )
            # Commit happens automatically on successful exit of the 'with uow:' block

    except Exception as e:
        # This catches errors initializing the UoW or during its exit
        error_count += 1
        log.exception("Error during Task 1 Unit of Work execution", error=str(e))

    log.info(
        "Task 1 Summary",
        inserted=inserted_count,
        skipped=skipped_count,
        errors=error_count,
    )
    return inserted_count, skipped_count, error_count
