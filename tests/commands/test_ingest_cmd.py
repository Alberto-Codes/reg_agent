
from typer.testing import CliRunner

# Import the main Typer app from your cli module
from reg_agent.cli import app

# Create a runner instance - IMPORTANT: set mix_stderr=False
runner = CliRunner(mix_stderr=False)


def test_ingest_run_success(tmp_path, mocker):
    """Test the happy path for 'reg-agent ingest run' command."""
    source_dir = tmp_path / "cli_test_source"
    source_dir.mkdir()
    db_file = tmp_path / "cli_test.db"

    # Mock the underlying function to avoid actual ingestion
    mock_ingest_files = mocker.patch("reg_agent.commands.ingest_cmd.ingest_files")

    # Invoke the command
    result = runner.invoke(
        app,
        [
            "ingest",
            "run",
            str(source_dir),
            "--db-path",
            str(db_file),
        ],
    )

    # Assertions
    assert result.exit_code == 0, (
        f"CLI exited with code {result.exit_code}\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    assert result.stderr == "", (
        f"Stderr should be empty on success, got:\n{result.stderr}"
    )
    # Check if the mocked function was called correctly
    mock_ingest_files.assert_called_once_with(
        source_dir=source_dir.resolve(),  # Command resolves the path
        db_file=db_file.resolve(),  # Command resolves the path
    )


def test_ingest_run_source_dir_not_exists(tmp_path):
    """Test 'reg-agent ingest run' when source directory doesn't exist."""
    non_existent_dir = tmp_path / "not_real"
    db_file = tmp_path / "cli_fail.db"

    result = runner.invoke(
        app,
        [
            "ingest",
            "run",
            str(non_existent_dir),
            "--db-path",
            str(db_file),
        ],
    )

    # Typer handles the 'exists=True' check and exits
    assert result.exit_code != 0, (
        "CLI should exit with non-zero code for non-existent source"
    )
    # Check stderr for the error message (Typer/Click provides this)
    assert "Invalid value for 'SOURCE_DIR'" in result.stderr
    assert "Directory" in result.stderr
    # assert str(non_existent_dir) in result.stderr # The path itself isn't always in the stderr
    assert "does not exist." in result.stderr  # Check for the core message


def test_ingest_run_source_is_file(tmp_path):
    """Test 'reg-agent ingest run' when source is a file, not a directory."""
    source_file = tmp_path / "source_is_a_file.txt"
    source_file.touch()
    db_file = tmp_path / "cli_fail_file.db"

    result = runner.invoke(
        app,
        [
            "ingest",
            "run",
            str(source_file),
            "--db-path",
            str(db_file),
        ],
    )

    # Typer handles the 'dir_okay=True, file_okay=False' check
    assert result.exit_code != 0, "CLI should exit with non-zero code for file source"
    assert "Invalid value for 'SOURCE_DIR'" in result.stderr
    assert "is a file." in result.stderr  # Added period
