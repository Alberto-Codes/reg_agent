from pathlib import Path
from typing import Optional

import structlog
import typer
import rich # Import rich for better output

from reg_agent.core.db.connection import DEFAULT_DB_FILE
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline

log = structlog.get_logger()

# Create a Typer app for this command module
app = typer.Typer()


@app.command(
    name="run", help="Ingest files from a source directory into the DuckDB database."
)
async def run_ingestion(
    source_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Directory containing files to ingest.",
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help="Path to the DuckDB database file.",
        resolve_path=True,
    ),
    recreate_db: bool = typer.Option(
        False,
        "--recreate-db",
        help="Delete the existing database file before ingestion.",
    ),
):
    """CLI command to run the file ingestion pipeline."""
    db_file = db_path or DEFAULT_DB_FILE

    log.info(
        "CLI command received",
        command="ingest run",
        source_dir=str(source_dir),
        db_path=str(db_file),
        recreate_db=recreate_db,
    )

    # This check is redundant as typer handles exists=True and dir_okay=True
    # if not source_dir.is_dir(): # Double-check, though typer should handle exists=True
    #     log.error("Source path is not a valid directory", path=str(source_dir))
    #     raise typer.BadParameter("Source path must be a directory.")

    if recreate_db and db_file.exists():
        log.warning("Recreating database file", path=str(db_file))
        try:
            db_file.unlink()
        except OSError as e:
            log.error("Failed to delete existing database file", error=str(e))
            raise typer.Exit(code=1)

    # Ensure parent directory for db exists if a custom path is given
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover
        log.error(
            "Failed to create parent directory for database file",
            path=str(db_file.parent),
            error=str(e),
        )
        # Consider this a critical failure
        raise typer.Exit(code=1)

    log.info("Starting ingestion pipeline...")
    pipeline_results = None # Initialize
    try:
        # Directly await the async pipeline function
        pipeline_results = await run_ingestion_pipeline(source_dir=source_dir, db_file=db_file)
        log.info("Ingestion pipeline finished.")
    except Exception as e:
        # Catch potential exceptions during pipeline execution
        log.exception("Ingestion pipeline failed with an error.", error=str(e))
        raise typer.Exit(code=1)

    # --- Report Error Details --- #
    if pipeline_results:
        task_3_results = pipeline_results.get("task_3", {})
        error_details = task_3_results.get("error_details", [])

        if error_details:
            rich.print("\n[bold red]Errors occurred during Task 3 (Metadata Extraction):[/]")
            for error in error_details:
                rich.print(f"  - File: [cyan]{error.get('filename', 'N/A')}[/]")
                rich.print(f"    Status: [yellow]{error.get('status', 'Unknown')}[/]")
                rich.print(f"    Error: [red]{error.get('error_message', 'Unknown error')}[/]")
                # Optional: include record_id if needed
                # rich.print(f"    Record ID: {error.get('record_id', 'N/A')}")
            rich.print("[bold red]Check logs for full tracebacks.[/]")

    else:
        log.warning("Pipeline did not return results.")


# You might add other ingest-related commands here later, like 'clear' or 'status'

if __name__ == "__main__":  # pragma: no cover
    # This allows running the command module directly for testing (optional)
    app()
