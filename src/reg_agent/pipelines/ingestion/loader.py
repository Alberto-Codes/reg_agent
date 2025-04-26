import datetime
import time
from pathlib import Path

import duckdb
import structlog

from reg_agent.core.db.connection import DEFAULT_DB_FILE, connect_db

log = structlog.get_logger()


def ingest_files(source_dir: Path, db_file: Path = DEFAULT_DB_FILE):
    """Scans a directory and ingests files into the DuckDB database.

    Args:
        source_dir: The directory containing files to ingest.
        db_file: The path to the DuckDB database file.
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

    try:
        con = connect_db(db_file=db_file)
        log.debug("Database connection established for ingestion.")

        # Prepare insert statement
        # Using prepared statements is generally safer and can be faster
        # Using INSERT OR IGNORE to skip duplicates based on PRIMARY KEY (source_path)
        insert_sql = """
            INSERT OR IGNORE INTO files (source_path, filename, blob, size_bytes, last_modified_ts)
            VALUES (?, ?, ?, ?, ?);
            """

        for file_path in source_dir.rglob("*"):  # Recursive glob to find all files
            if file_path.is_file():
                try:
                    # 1. Get Metadata
                    file_stat = file_path.stat()
                    source_path_str = str(
                        file_path.resolve()
                    )  # Use absolute path as PK
                    filename = file_path.name
                    size_bytes = file_stat.st_size
                    # Convert modification time to UTC datetime
                    last_modified_ts = datetime.datetime.fromtimestamp(
                        file_stat.st_mtime, tz=datetime.timezone.utc
                    )

                    # 2. Read Blob
                    with open(file_path, "rb") as f:
                        blob_content = f.read()

                    # 3. Insert Record
                    # DuckDB Python client automatically handles parameter binding
                    cur = con.execute(
                        insert_sql,
                        [
                            source_path_str,
                            filename,
                            blob_content,
                            size_bytes,
                            last_modified_ts,
                        ],
                    )

                    if cur.rowcount > 0:
                        inserted_count += 1
                        log.debug("Inserted file", path=source_path_str)
                    else:
                        skipped_count += 1
                        log.debug("Skipped existing file", path=source_path_str)

                except OSError as e:
                    error_count += 1
                    log.error(
                        "Error processing file", file=str(file_path), error=str(e)
                    )
                except Exception:
                    error_count += 1
                    log.exception(
                        "Unexpected error processing file", file=str(file_path)
                    )

        # Commit changes (DuckDB typically auto-commits, but explicit commit is good practice)
        con.commit()
        log.debug("Committed changes to database.")

    except duckdb.Error as e:
        error_count += 1  # Count DB connection/commit errors
        log.exception("Database error during ingestion", error=str(e), exc_info=True)
    except Exception:
        error_count += 1  # Count other unexpected errors
        log.exception("Unexpected error during ingestion process", exc_info=True)
    finally:
        if "con" in locals() and con:
            con.close()
            log.debug("Database connection closed after ingestion attempt.")

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
    # Create a dummy directory and file for testing
    EXAMPLE_DIR = Path("./example_ingestion_source")
    EXAMPLE_DIR.mkdir(exist_ok=True)
    dummy_file = EXAMPLE_DIR / "my_test_file.txt"
    dummy_file.write_text("This is the content of the test file.\n")

    # Create a subdirectory and another file
    sub_dir = EXAMPLE_DIR / "subdir"
    sub_dir.mkdir(exist_ok=True)
    dummy_file_2 = sub_dir / "another_file.log"
    dummy_file_2.write_text("Log line 1\nLog line 2")

    # Define a temporary DB for this example run
    example_db_path = Path("./db/example_ingestion_run.db")
    if example_db_path.exists():
        example_db_path.unlink()  # Clean up previous run

    log.info(
        "Ingesting example files", source=str(EXAMPLE_DIR), db=str(example_db_path)
    )
    ingest_files(EXAMPLE_DIR, db_file=example_db_path)

    log.info("Checking database content after example ingestion...")
    try:
        conn = connect_db(db_file=example_db_path)
        results = conn.execute(
            "SELECT source_path, filename, size_bytes FROM files"
        ).fetchall()
        log.info("Files found in DB", results=results)
        conn.close()
    except Exception:
        log.exception("Error checking example DB content")

    # Clean up dummy files/dir
    # dummy_file.unlink()
    # dummy_file_2.unlink()
    # sub_dir.rmdir()
    # EXAMPLE_DIR.rmdir() # Be careful with rmdir if other files exist
    # print("Cleaned up example files and directory.")
