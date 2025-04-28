import argparse
import asyncio
from pathlib import Path

import structlog  # For logging in main

from reg_agent.core.db.connection import DEFAULT_DB_FILE

# Directly import the pipeline function
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline

log = structlog.get_logger()


async def main_pipeline_runner(args: argparse.Namespace):
    """Async wrapper to run the pipeline with parsed args."""
    db_file = args.db_path or DEFAULT_DB_FILE
    source_dir = args.source_dir

    log.info(
        "CLI command received (argparse)",
        command="ingest run",
        source_dir=str(source_dir),
        db_path=str(db_file),
        recreate_db=args.recreate_db,
    )

    if args.recreate_db and db_file.exists():
        log.warning("Recreating database file", path=str(db_file))
        try:
            db_file.unlink()
        except OSError as e:
            log.error("Failed to delete existing database file", error=str(e))
            # Use sys.exit for argparse
            import sys

            sys.exit(1)

    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.error(
            "Failed to create parent directory for database file",
            path=str(db_file.parent),
            error=str(e),
        )
        import sys

        sys.exit(1)

    log.info("Starting ingestion pipeline...")
    pipeline_results = None
    try:
        pipeline_results = await run_ingestion_pipeline(
            source_dir=source_dir, db_file=db_file
        )
        log.info("Ingestion pipeline finished.")
    except Exception as e:
        log.exception("Ingestion pipeline failed with an error.", error=str(e))
        import sys

        sys.exit(1)

    # Optional: Add result reporting here if needed, similar to Typer version
    if pipeline_results:
        log.info("Pipeline results:", results=pipeline_results)
    else:
        log.warning("Pipeline did not return results.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest files into the document knowledge base."
    )
    parser.add_argument(
        "source_dir", type=Path, help="Directory containing files to ingest."
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        type=Path,
        default=None,  # Handled later with DEFAULT_DB_FILE
        help="Path to the DuckDB database file.",
    )
    parser.add_argument(
        "--recreate-db",
        action="store_true",
        help="Delete the existing database file before ingestion.",
    )

    args = parser.parse_args()

    # Basic validation for source_dir (argparse doesn't have exists=True)
    if not args.source_dir.is_dir():
        print(
            f"Error: Source directory not found or not a directory: {args.source_dir}"
        )
        import sys

        sys.exit(1)

    asyncio.run(main_pipeline_runner(args))
