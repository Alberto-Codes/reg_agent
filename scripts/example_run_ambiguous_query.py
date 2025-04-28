# scripts/example_run_ambiguous_query.py

import asyncio
import sys
from pathlib import Path

# Add src directory to sys.path to allow absolute imports
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlmodel import Session

from reg_agent.agents.query_agent import query_agent  # Import the agent instance
from reg_agent.config import log  # Use configured logger

# Adjust DB path relative to project root if needed, or use config
# from reg_agent.config import settings # If settings has db_path
from reg_agent.core.db.connection import get_engine
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.tools.duckdb_tool import DuckDBToolDeps  # Import dependency class

# --- Example Runner Function ---


async def run_query_agent_example(user_query: str, repo: DocumentRepository):
    """Runs the query agent with the given query and repository."""
    log.info("Running query agent example", user_query=user_query)

    # Create the dependencies instance
    deps = DuckDBToolDeps(repo=repo)

    try:
        # Run the agent
        # Use capture_run_messages to inspect the conversation if needed for debugging
        # from pydantic_ai import capture_run_messages
        # with capture_run_messages() as captured_messages:
        result = await query_agent.run(user_query, deps=deps)

        # Process the result (which will be a string by default)
        log.info("Agent finished successfully.", output=result.output)
        print("\n-- Agent Output --")
        print(result.output)
        print("-----------------")

        # If debugging tool calls:
        # print("\n-- Captured Messages --")
        # for msg in captured_messages:
        #     print(msg)
        # print("----------------------")

    except Exception as e:
        log.exception("Error running query agent", error=e)
        print(f"\nAn error occurred: {e}")


# --- Main Execution Block ---

if __name__ == "__main__":
    # Hardcoded ambiguous query for testing
    query_to_run = "Tell me about Wells Fargo cases"

    # --- Database Setup ---
    # Use a default DB path relative to project root or load from config
    db_dir = project_root / "db"
    db_file = db_dir / "regulations.db"
    db_dir.mkdir(exist_ok=True)
    # Alternatively, load from config: db_file = settings.db_file

    log.info("Connecting to database", db_path=str(db_file))
    if not db_file.exists():
        log.error("Database file not found. Run ingestion first?", db_path=str(db_file))
        sys.exit(1)

    # Pass the Path object directly
    engine = get_engine(db_file=db_file)

    # Create session and repository
    with Session(engine) as session:
        repository = DocumentRepository(session=session)
        log.info("Repository initialized.")

        # Run the example
        print(f"Running agent with hardcoded ambiguous query: '{query_to_run}'")
        asyncio.run(run_query_agent_example(query_to_run, repository))

    log.info("Script finished.")
