from pathlib import Path
from typing_extensions import Annotated

import typer
import structlog

from reg_agent.pipelines.ingestion.loader import ingest_files
from reg_agent.core.db.connection import DEFAULT_DB_FILE

log = structlog.get_logger()

# Create a Typer app for this command module
app = typer.Typer()

@app.command(
    name="run",
    help="Ingest files from a source directory into the DuckDB database."
)
def run_ingestion(
    source_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Directory containing files to ingest.",
        ),
    ],
    db_path: Annotated[
        Path,
        typer.Option(
            writable=True,
            resolve_path=True,
            help=f"Path to the DuckDB database file. Defaults to: {DEFAULT_DB_FILE}"
        )
    ] = DEFAULT_DB_FILE,
):
    """CLI command to run the file ingestion pipeline."""
    log.info("CLI command received", command="ingest run", source_dir=str(source_dir), db_path=str(db_path))
    ingest_files(source_dir=source_dir, db_file=db_path)
    log.info("Ingestion command finished.")

# You might add other ingest-related commands here later, like 'clear' or 'status'

if __name__ == "__main__": # pragma: no cover
    # This allows running the command module directly for testing (optional)
    app() 