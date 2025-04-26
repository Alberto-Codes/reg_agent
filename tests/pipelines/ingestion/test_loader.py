import datetime
from pathlib import Path
from unittest.mock import MagicMock  # Import MagicMock

import duckdb  # Import duckdb for duckdb.Error

from reg_agent.core.db.connection import connect_db
from reg_agent.pipelines.ingestion.loader import ingest_files


def _create_dummy_files(base_dir: Path, file_specs: list[tuple[str, str]]):
    """Helper to create dummy files/directories."""
    created_paths = []
    for rel_path_str, content in file_specs:
        file_path = base_dir / rel_path_str
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        created_paths.append(file_path.resolve())
        # Add a tiny delay to ensure distinct modification times if needed
        # time.sleep(0.01)
    return created_paths


def test_ingest_files_happy_path(tmp_path):
    """Test basic ingestion of a few files."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_ingest.db"

    # Create dummy files
    file_specs = [
        ("file1.txt", "content1"),
        ("subdir/file2.log", "log content"),
        ("file3.bin", "binary\0content"),  # Include null byte
    ]
    expected_paths = _create_dummy_files(source_dir, file_specs)

    # Run ingestion
    ingest_files(source_dir, db_file=db_file)

    # Verify database content
    con = connect_db(db_file=db_file)
    results = con.execute(
        "SELECT source_path, filename, blob, size_bytes, last_modified_ts FROM files ORDER BY source_path"
    ).fetchall()
    con.close()

    assert len(results) == len(file_specs), (
        f"Expected {len(file_specs)} files, found {len(results)}"
    )

    # Check details of each inserted file
    results_map = {
        Path(row[0]): row[1:] for row in results
    }  # Map path string back to Path for comparison
    assert set(results_map.keys()) == set(expected_paths), (
        "Inserted paths do not match expected paths"
    )

    for path in expected_paths:
        filename, blob, size, ts_from_db = results_map[path]
        original_content = path.read_bytes()
        original_mtime_utc = datetime.datetime.fromtimestamp(
            path.stat().st_mtime, tz=datetime.timezone.utc
        )

        assert filename == path.name, f"Filename mismatch for {path}"
        assert blob == original_content, f"Blob content mismatch for {path}"
        assert size == len(original_content), f"Size mismatch for {path}"
        assert isinstance(ts_from_db, datetime.datetime), (
            f"Timestamp is not a datetime object for {path}"
        )

        # Check if the timestamp from DB, when assumed to be UTC (or converted),
        # matches the original UTC timestamp within a small tolerance.
        # DuckDB might return naive datetime; we compare the actual time value.
        if ts_from_db.tzinfo is None:
            # Assume the naive datetime from DB represents UTC time
            ts_from_db_utc = ts_from_db.replace(tzinfo=datetime.timezone.utc)
        else:
            # If it is timezone-aware, convert it to UTC just in case
            ts_from_db_utc = ts_from_db.astimezone(datetime.timezone.utc)

        # Compare timestamps with a tolerance (e.g., 1 second)
        time_difference = abs(ts_from_db_utc - original_mtime_utc)
        assert time_difference < datetime.timedelta(seconds=1), (
            f"Timestamp mismatch for {path}. DB: {ts_from_db_utc}, Original: {original_mtime_utc}"
        )


def test_ingest_files_duplicates_skipped(tmp_path):
    """Test that running ingestion again skips existing files."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_duplicates.db"

    # Create one dummy file
    file_specs = [("file1.txt", "initial content")]
    _create_dummy_files(source_dir, file_specs)

    # Run ingestion first time
    ingest_files(source_dir, db_file=db_file)

    # Verify one file inserted
    con = connect_db(db_file=db_file)
    count1 = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert count1 == 1, "Should have 1 file after first ingestion"
    con.close()

    # Modify the file content (optional, shows blob doesn't get updated by default)
    # (Path(source_dir / "file1.txt")).write_text("updated content")
    # time.sleep(0.1) # Ensure mtime changes if testing mtime update logic later

    # Run ingestion second time
    # Capture logs or check summary log output if needed to verify skip count
    ingest_files(source_dir, db_file=db_file)

    # Verify still only one file (due to INSERT OR IGNORE on source_path)
    con = connect_db(db_file=db_file)
    count2 = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert count2 == 1, (
        "Should still have only 1 file after second ingestion (duplicate skipped)"
    )
    # Optionally check blob if update logic was added
    # blob_content = con.execute("SELECT blob FROM files").fetchone()[0]
    # assert blob_content == b"initial content", "Blob should not have been updated"
    con.close()


def test_ingest_files_empty_directory(tmp_path):
    """Test ingestion with an empty source directory."""
    source_dir = tmp_path / "empty_source"
    source_dir.mkdir()  # Ensure directory exists but is empty
    db_file = tmp_path / "test_empty.db"

    ingest_files(source_dir, db_file=db_file)

    # Verify database is empty
    con = connect_db(db_file=db_file)
    count = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert count == 0, "Database should be empty after ingesting from empty directory"
    con.close()


def test_ingest_files_nonexistent_directory(tmp_path, caplog):
    """Test ingestion with a source directory that does not exist."""
    source_dir = tmp_path / "nonexistent_source"
    db_file = tmp_path / "test_nonexistent.db"

    # Ensure the directory does not exist
    assert not source_dir.exists()

    # Capture log messages
    caplog.set_level("ERROR")

    ingest_files(source_dir, db_file=db_file)

    # Verify an error was logged
    assert "Source directory does not exist" in caplog.text

    # Verify the database file might not even be created or is empty if created
    if db_file.exists():
        con = connect_db(db_file=db_file)
        count = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert count == 0, "Database should be empty if source dir doesn't exist"
        con.close()
    # else: pass - file not being created is also acceptable failure mode here


# --- Simplified Error Handling Tests ---


def test_ingest_files_db_error_on_connect(tmp_path, mocker, caplog):
    """Test handling DuckDB error during connect (caught by outer except)."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_dberror_connect.db"
    _create_dummy_files(source_dir, [("file1.txt", "content")])

    # Mock connect_db itself to raise an error
    mocker.patch(
        "reg_agent.pipelines.ingestion.loader.connect_db",
        side_effect=duckdb.IOException("Cannot access DB file"),
    )

    caplog.set_level("ERROR")
    ingest_files(source_dir, db_file=db_file)

    # Should be caught by the outer duckdb.Error handler
    assert "Database error during ingestion" in caplog.text
    assert "Cannot access DB file" in caplog.text


def test_ingest_files_general_exception_outer(tmp_path, mocker, caplog):
    """Test handling general Exception during setup/commit (caught by outer except)."""
    source_dir = tmp_path / "source"
    db_file = tmp_path / "test_exception_outer.db"
    _create_dummy_files(source_dir, [("file1.txt", "content")])

    # Mock the commit method to raise an error
    mock_conn = mocker.MagicMock()
    mock_conn.commit.side_effect = Exception("Commit failed unexpectedly")
    # Ensure close exists
    mock_conn.close = MagicMock()
    mocker.patch(
        "reg_agent.pipelines.ingestion.loader.connect_db", return_value=mock_conn
    )

    caplog.set_level("ERROR")
    ingest_files(source_dir, db_file=db_file)

    # Should be caught by the outer Exception handler
    assert "Unexpected error during ingestion process" in caplog.text
    assert "Commit failed unexpectedly" in caplog.text
    mock_conn.close.assert_called_once()
