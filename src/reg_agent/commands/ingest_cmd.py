from pathlib import Path
from typing import Optional

import structlog
import typer
from typing_extensions import Annotated
import asyncio

from reg_agent.core.db.connection import DEFAULT_DB_FILE
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline

log = structlog.get_logger()

# Create a Typer app for this command module
app = typer.Typer()


@app.command(
    name="run", help="Ingest files from a source directory into the DuckDB database."
)
def run_ingestion(
    source_dir: Path =
        typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Directory containing files to ingest.",
        ),
    db_path: Optional[Path] =
        typer.Option(
            None,
            "--db",
            help="Path to the DuckDB database file.",
            resolve_path=True,
        ),
    recreate_db: bool =
        typer.Option(
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

    if not source_dir.is_dir(): # Double-check, though typer should handle exists=True
        log.error("Source path is not a valid directory", path=str(source_dir))
        raise typer.BadParameter("Source path must be a directory.")

    if recreate_db and db_file.exists():
        log.warning("Deleting existing database file", path=str(db_file))
        try:
            db_file.unlink()
        except OSError as e:
            log.error("Failed to delete existing database file", path=str(db_file), error=str(e))
            # Decide if this is critical - for now, log and continue, the get_engine might fail later
        except Exception as e:
             log.exception("Unexpected error deleting database file", path=str(db_file), error=str(e))

    # Ensure parent directory for db exists if a custom path is given
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.error("Failed to create parent directory for database file", path=str(db_file.parent), error=str(e))
        # Consider this a critical failure
        raise typer.Exit(code=1)

    try:
        # Run the synchronous pipeline orchestrator function directly
        run_ingestion_pipeline(source_dir=source_dir, db_file=db_file)
        log.info("Ingestion command finished.")
    except Exception as e:
        log.exception("Ingestion process failed unexpectedly.", error=str(e))
        raise typer.Exit(code=1)


# You might add other ingest-related commands here later, like 'clear' or 'status'

if __name__ == "__main__":  # pragma: no cover
    # This allows running the command module directly for testing (optional)
    app()
