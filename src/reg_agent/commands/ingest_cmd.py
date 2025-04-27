from pathlib import Path

import structlog
import typer
from typing_extensions import Annotated

from reg_agent.core.db.connection import DEFAULT_DB_FILE
from reg_agent.pipelines.ingestion.loader import ingest_files

log = structlog.get_logger()

# Create a Typer app for this command module
app = typer.Typer()


@app.command(
    name="run", help="Ingest files from a source directory into the DuckDB database."
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
            help="Path to the DuckDB database file.",
            default_factory=lambda: DEFAULT_DB_FILE,
            writable=True,
            resolve_path=True,
        ),
    ],
    recreate_db: Annotated[
        bool,
        typer.Option(
            "--recreate-db",
            help="Delete the existing database file before ingestion.",
        ),
    ] = False,
):
    """CLI command to run the file ingestion pipeline."""
    log.info(
        "CLI command received",
        command="ingest run",
        source_dir=str(source_dir),
        db_path=str(db_path),
        recreate_db=recreate_db,
    )

    if recreate_db:
        try:
            resolved_db_path = db_path.resolve()
            if resolved_db_path.exists() and resolved_db_path.is_file():
                log.warning(
                    "Deleting existing database file", path=str(resolved_db_path)
                )
                resolved_db_path.unlink()
            else:
                log.info(
                    "Database file does not exist, skipping deletion.",
                    path=str(resolved_db_path),
                )
        except OSError as e:
            log.exception(
                "Failed to delete existing database file. Proceeding without deletion.",
                path=str(resolved_db_path),
                error=str(e),
            )
        except Exception as e:
            log.exception(
                "An unexpected error occurred during database deletion. Proceeding without deletion.",
                path=str(resolved_db_path),
                error=str(e),
            )

    try:
        ingest_files(source_dir=source_dir, db_file=db_path)
        log.info("Ingestion command finished.")
    except Exception as e:
        log.exception("Ingestion process failed unexpectedly.", error=str(e))
        raise typer.Exit(code=1)


# You might add other ingest-related commands here later, like 'clear' or 'status'

if __name__ == "__main__":  # pragma: no cover
    # This allows running the command module directly for testing (optional)
    app()
