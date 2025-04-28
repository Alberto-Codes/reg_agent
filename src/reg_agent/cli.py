import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from sqlmodel import Session, create_engine

from reg_agent.config import log  # Use centralized log
from reg_agent.core.db.connection import DEFAULT_DB_FILE
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.pipelines.ingestion.run import run_ingestion_pipeline
from reg_agent.pipelines.query_and_cag_graph import (
    End,
    QueryAgentNode,
    QueryAndCAGState,
    create_query_cag_graph,
)
from reg_agent.tools.duckdb_tool import DuckDBToolDeps

# Load environment variables (especially for LLM config) early
load_dotenv()

# Use Typer for CLI application
app = typer.Typer()

# Use existing structlog logger
# log = structlog.get_logger() # Already imported from config


@app.command(name="ingest")
def ingest_files(
    source_dir: Path = typer.Argument(
        ..., help="Directory containing files to ingest.", exists=True, file_okay=False
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help=f"Path to the DuckDB database file (default: {DEFAULT_DB_FILE})",
    ),
    recreate_db: bool = typer.Option(
        False,
        "--recreate-db",
        help="Delete the existing database file before ingestion.",
    ),
):
    """
    Ingests files from a source directory into the document knowledge base.
    """
    db_file = db_path or DEFAULT_DB_FILE

    log.info(
        "CLI command received",
        command="ingest",
        source_dir=str(source_dir),
        db_path=str(db_file),
        recreate_db=recreate_db,
    )

    if recreate_db and db_file.exists():
        log.warning("Recreating database file", path=str(db_file))
        try:
            db_file.unlink()
        except OSError as e:
            log.error("Failed to delete existing database file", error=str(e))
            raise typer.Exit(code=1)

    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.error(
            "Failed to create parent directory for database file",
            path=str(db_file.parent),
            error=str(e),
        )
        raise typer.Exit(code=1)

    log.info("Starting ingestion pipeline...")
    pipeline_results = None
    try:
        # Need to run the async function
        pipeline_results = asyncio.run(
            run_ingestion_pipeline(source_dir=source_dir, db_file=db_file)
        )
        log.info("Ingestion pipeline finished.")
    except Exception as e:
        log.exception("Ingestion pipeline failed with an error.", error=str(e))
        raise typer.Exit(code=1)

    if pipeline_results:
        log.info("Pipeline results:", results=pipeline_results)
        typer.echo("Ingestion completed successfully.")
    else:
        log.warning("Pipeline did not return results.")
        typer.echo("Ingestion completed, but no results were returned.")


async def run_query_pipeline_async(user_query: str, db_path: Path):
    """Async function to run the Query -> CAG pipeline graph."""
    log.info("Starting Query-CAG pipeline run", query=user_query, db=str(db_path))

    if not db_path.exists():
        log.error("Database file not found", path=str(db_path))
        typer.echo(
            f"Error: Database not found at {db_path}. Please run ingestion first."
        )
        raise typer.Exit(code=1)

    engine = create_engine(f"duckdb:///{db_path}")
    graph_result = None
    try:
        with Session(engine) as session:
            repo = DocumentRepository(session)
            deps = DuckDBToolDeps(repo=repo)

            graph = create_query_cag_graph()
            initial_state = QueryAndCAGState(user_query=user_query, deps=deps)

            log.info("Executing graph...")
            graph_result = await graph.run(
                QueryAgentNode(),  # Start with an instance of the first node
                state=initial_state,
            )
            log.info("Graph execution finished.")

            typer.echo("\n--- Final Output ---")
            if isinstance(graph_result, End):
                typer.echo(graph_result.output)
            elif (
                graph_result
                and hasattr(graph_result, "state")
                and graph_result.state
                and graph_result.state.final_output
            ):
                log.warning(
                    "Graph finished but result was not End node",
                    result_type=type(graph_result),
                )
                typer.echo(graph_result.state.final_output)
            else:
                typer.echo(
                    "Graph did not produce a final output or ended unexpectedly."
                )
                log.warning("Unexpected graph result", result=graph_result)

    except Exception as e:
        log.exception("Pipeline execution failed", error=str(e))
        typer.echo(f"\nAn error occurred during pipeline execution: {e}")
        raise typer.Exit(code=1)
    finally:
        if engine:
            engine.dispose()
            log.info("Database engine disposed.")


@app.command(name="query")
def query_documents(
    user_query: Optional[str] = typer.Argument(
        None,
        help="The query to ask the agent system. If omitted, runs in interactive mode.",
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help=f"Path to the DuckDB database file (default: {DEFAULT_DB_FILE})",
    ),
):
    """
    Runs the Query-CAG pipeline with the provided user query.
    If no query is provided as an argument, it enters interactive mode.
    """
    db_file = db_path or DEFAULT_DB_FILE

    # Handle interactive mode
    if user_query is None:
        typer.echo("Entering interactive query mode. Type 'exit' or 'quit' to leave.")
        while True:
            user_query = typer.prompt("Query")
            # Check if prompt returned None (e.g., Ctrl+C)
            if user_query is None:
                typer.echo("\nPrompt cancelled. Exiting interactive mode.")
                break
            # Check for exit command
            if user_query.lower() in ["exit", "quit"]:
                typer.echo("Exiting interactive mode.")
                break
            if not user_query:
                typer.echo("Please enter a query or type 'exit'.")
                continue

            log.info(
                "CLI command received (interactive)",
                command="query",
                query=user_query,
                db_path=str(db_file),
            )
            # Run the async pipeline for the interactive query
            asyncio.run(
                run_query_pipeline_async(user_query=user_query, db_path=db_file)
            )
            typer.echo("\n---------------------")  # Separator for interactive mode
        # Exit after the loop finishes (user typed exit/quit)
        raise typer.Exit()
    else:
        # Run for non-interactive query provided as argument
        log.info(
            "CLI command received (argument)",
            command="query",
            query=user_query,
            db_path=str(db_file),
        )
        asyncio.run(run_query_pipeline_async(user_query=user_query, db_path=db_file))


if __name__ == "__main__":
    # Configure Logfire if enabled
    if os.environ.get("ENABLE_LOGFIRE", "false").lower() == "true":
        try:
            import logfire

            logfire.configure()
            log.info("Logfire configured for CLI.")
        except ImportError:
            log.warning("Logfire import failed, ensure installed if enabled.")
        except Exception as lf_err:
            log.error("Logfire configuration failed", error=str(lf_err))

    app()
