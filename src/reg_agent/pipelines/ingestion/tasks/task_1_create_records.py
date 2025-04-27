# src/reg_agent/pipelines/ingestion/tasks/task_1_create_records.py

import datetime
import time
from pathlib import Path

import structlog
from sqlalchemy.engine import Engine

from reg_agent.core.db.connection import get_session
from reg_agent.core.db.models import FileRecord, FileStatus
from reg_agent.core.db.repositories import FileRepository
from reg_agent.utils.timing import log_task_duration

log = structlog.get_logger()


@log_task_duration("task_1_create_records")
def run_task_1(engine: Engine, source_dir: Path):
    """Scans the source directory and creates initial FileRecord entries
    in the database for new files found (Synchronous Version).

    Args:
        engine: The SQLAlchemy SyncEngine for database interaction.
        source_dir: The directory containing files to ingest.

    Returns:
        Tuple[int, int, int]: inserted_count, skipped_count, error_count
    """
    inserted_count = 0
    skipped_count = 0
    error_count = 0

    try:
        # Use the synchronous session manager
        with get_session(engine=engine) as session:
            file_repo = FileRepository(session)
            # Pathlib iteration is sync
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    source_path_str = str(file_path.resolve())
                    try:
                        # Call sync existence check directly
                        if file_repo.exists_by_source_path(source_path_str):
                            skipped_count += 1
                            log.debug("Skipped existing file", path=source_path_str)
                            continue

                        # File I/O and stat remain sync
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

                        # Call sync add directly
                        session.add(new_record)
                        inserted_count += 1
                        log.debug("Staged new FileRecord", path=source_path_str, record_id=new_record.id)

                    except OSError as e:
                        error_count += 1
                        log.error(
                            "OS Error processing file during Task 1",
                            file=str(file_path),
                            error=str(e),
                        )
                    except Exception as e:
                        error_count += 1
                        log.exception(
                            "Unexpected error processing file during Task 1",
                            file=str(file_path),
                            error=str(e),
                        )

            # Commit happens automatically via sync context manager exit

    except Exception as e:
        error_count += 1
        log.exception("Error during Task 1 session or execution", error=str(e))

    # Log final summary counts
    log.info(
        "Task 1 Summary",
        inserted=inserted_count,
        skipped=skipped_count,
        errors=error_count
    )
    return inserted_count, skipped_count, error_count 