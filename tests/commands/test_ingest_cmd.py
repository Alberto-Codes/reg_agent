import pytest
from typer.testing import CliRunner
from pathlib import Path

# Import the main Typer app from your cli module
from reg_agent.cli import app # type: ignore

# Initialize runner to keep stdout and stderr separate
runner = CliRunner(mix_stderr=False)


def test_ingest_run_success(tmp_path, mocker):
    """Test the happy path for 'reg-agent ingest run' command."""
    source_dir = tmp_path / "cli_test_source"
    source_dir.mkdir()
    db_file = tmp_path / "cli_test.db"

    # Mock the underlying function WHERE IT IS USED in ingest_cmd.py
    mock_pipeline_run = mocker.patch(
        "reg_agent.commands.ingest_cmd.run_ingestion_pipeline"
    )

    result = runner.invoke(
        app,
        [
            "ingest",
            "run",
            str(source_dir),
            "--db",
            str(db_file),
        ],
    )

    # Primary assertions: exit code is 0 and the mocked function was called
    assert result.exit_code == 0, f"CLI failed with stdout: {result.stdout}, stderr: {result.stderr}"
    mock_pipeline_run.assert_called_once_with(
        source_dir=source_dir.resolve(), db_file=db_file.resolve()
    )
    # Optional: Check log output if necessary, but less critical when mocking
    # assert "Ingestion command finished." in result.output # Check combined output


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
            "--db",
            str(db_file),
        ],
    )

    assert result.exit_code != 0, (
        "CLI should exit with non-zero code for non-existent source"
    )
    # Simplify assertion: check for key phrase in stderr
    assert "does not exist." in result.stderr


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
            "--db",
            str(db_file),
        ],
    )

    assert result.exit_code != 0, "CLI should exit with non-zero code for file source"
    # Simplify assertion: check for key phrase in stderr
    assert "is a file." in result.stderr
