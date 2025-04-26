import duckdb

# Adjust import path assuming pytest runs from project root
from reg_agent.core.db.connection import connect_db

# Expected columns and their general types (DuckDB types can be complex)
# Mapping DuckDB types to broader categories for easier testing
EXPECTED_COLUMNS = {
    "source_path": "VARCHAR",
    "filename": "VARCHAR",
    "blob": "BLOB",
    "size_bytes": "BIGINT",  # Or maybe INTEGER depending on exact DuckDB version/schema
    "last_modified_ts": "TIMESTAMP",
}


def test_connect_db_creates_table_and_file(tmp_path):
    """Tests that connect_db creates the DB file and the 'files' table correctly."""
    # Use a temporary path provided by pytest for the database file
    test_db_file = tmp_path / "test_archive.db"

    assert not test_db_file.exists(), "Test DB file should not exist initially"

    con = None  # Initialize con to None
    try:
        con = connect_db(db_file=test_db_file)
        assert isinstance(con, duckdb.DuckDBPyConnection), (
            "Should return a DuckDB connection"
        )
        assert test_db_file.exists(), "connect_db should create the DB file"
        assert test_db_file.is_file(), "Created path should be a file"

        # Verify the 'files' table exists
        tables = con.execute("SHOW TABLES;").fetchall()
        assert ("files",) in tables, "'files' table should exist"

        # Verify the columns and types in the 'files' table
        # Query information schema (adjust query if needed for specific DuckDB versions)
        columns_info = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'files' ORDER BY ordinal_position;"
        ).fetchall()

        assert len(columns_info) == len(EXPECTED_COLUMNS), (
            f"Expected {len(EXPECTED_COLUMNS)} columns, found {len(columns_info)}"
        )

        # Check column names and rough types
        actual_columns = {name: type_str for name, type_str in columns_info}
        print(f"Actual columns: {actual_columns}")  # Debugging output
        assert set(actual_columns.keys()) == set(EXPECTED_COLUMNS.keys()), (
            "Column names do not match expected"
        )

        # Optionally, check types (be mindful of DuckDB type variations)
        for col_name, expected_type in EXPECTED_COLUMNS.items():
            # Simple check: Does the actual type string contain the expected base type?
            assert expected_type.upper() in actual_columns[col_name].upper(), (
                f"Column '{col_name}' type mismatch. Expected containing '{expected_type}', got '{actual_columns[col_name]}'"
            )

    finally:
        # Ensure the connection is closed even if assertions fail
        if con:
            con.close()
