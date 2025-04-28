# scripts/run_query_agent.py

import asyncio
import sys
from pathlib import Path

import rich
import structlog

# Add src directory to sys.path to allow absolute imports
project_root = Path(__file__).resolve().parents[1]
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from sqlmodel import Session

# Import the factory function and deps
from reg_agent.agents.query_agent import DuckDBToolDeps, create_query_agent
from reg_agent.config import log  # Use configured logger

# Adjust DB path relative to project root if needed, or use config
# from reg_agent.config import settings # If settings has db_path
from reg_agent.core.db.connection import get_engine  # Import DB utils
from reg_agent.core.db.repositories import DocumentRepository  # Import repo

log = structlog.get_logger()

# --- Main Execution Block ---


async def main():
    log.info("Configuring Logfire...")
    # We assume logfire is configured during agent import/creation
    # in query_agent.py if ENABLE_LOGFIRE is set

    # --- Database and Dependencies Setup ---
    project_root = Path(__file__).resolve().parents[1]  # Get project root
    db_dir = project_root / "db"
    db_file = db_dir / "regulations.db"
    db_dir.mkdir(exist_ok=True)
    log.info("Connecting to database", db_path=str(db_file))
    if not db_file.exists():
        log.error("Database file not found. Run ingestion first?", db_path=str(db_file))
        sys.exit(1)

    engine = get_engine(db_file=db_file)
    with Session(engine) as session:
        repository = DocumentRepository(session=session)
        tool_deps = DuckDBToolDeps(repo=repository)
        log.info("Repository and Tool Dependencies initialized.")

        # --- Create Agent Instance ---
        agent_instance = create_query_agent()
        log.info("Query agent instance created.")

        # --- Define the Query ---
        user_query = "Find documents for Wells Fargo Bank, N.A."
        log.info("Running query agent example", user_query=user_query)

        # --- Run the Agent ---
        log.info("Starting agent run...")
        result = await agent_instance.run(user_query, deps=tool_deps)
        log.info("Agent run finished.")

        print("\n-- Agent Output --")
        rich.print(result.output)
        print("-----------------")
        log.info("Script finished.")


if __name__ == "__main__":
    asyncio.run(main())
