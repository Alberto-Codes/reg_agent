from pathlib import Path

import duckdb
import structlog

# Initialize logger
log = structlog.get_logger()

# Define the root directory of the project
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
# Define the path to the database directory
DB_DIR = PROJECT_ROOT / "db"
# Define the default database file name
DEFAULT_DB_FILE = DB_DIR / "file_archive.db"


def connect_db(db_file: Path = DEFAULT_DB_FILE) -> duckdb.DuckDBPyConnection:
    """
    Connects to the DuckDB database file and ensures the 'files' table exists.

    Args:
        db_file: The path to the DuckDB database file.

    Returns:
        A connection object to the DuckDB database.
    """
    # Ensure the database directory exists
    DB_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=str(db_file), read_only=False)

    # Create the 'files' table if it doesn't exist based on the Gherkin spec
    con.execute("""
        CREATE TABLE IF NOT EXISTS files (
            source_path       VARCHAR PRIMARY KEY,
            filename          VARCHAR,
            blob              BLOB,
            size_bytes        BIGINT,
            last_modified_ts  TIMESTAMPTZ
        );
    """)
    return con


# Example of how to use it (optional, can be removed later)
if __name__ == "__main__":  # pragma: no cover
    # Use log.debug for detailed info, log.info for general status
    log.debug(
        "Project paths",
        project_root=str(PROJECT_ROOT),
        db_dir=str(DB_DIR),
        db_file=str(DEFAULT_DB_FILE),
    )
    try:
        connection = connect_db()
        log.info(
            "Database connection successful and 'files' table ensured.",
            db_file=str(DEFAULT_DB_FILE),
        )
        # Example query
        result = connection.execute("SELECT COUNT(*) FROM files").fetchone()
        count = result[0] if result else 0
        log.info("Current file count in DB", count=count)
        connection.close()
        log.debug("Database connection closed.")
    except Exception:
        # Use log.exception to include stack trace
        log.exception("An error occurred during DB connection example.")
