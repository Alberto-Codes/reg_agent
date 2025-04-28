# scripts/run_query_cag_pipeline.py
"""Example script to run the Query -> CAG graph pipeline."""

import asyncio
import os
from pathlib import Path  # Import Path

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

from reg_agent.config import log  # Import log from config

# Ensure necessary components are importable
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.pipelines.query_and_cag_graph import (
    End,
    QueryAgentNode,
    QueryAndCAGState,
    create_query_cag_graph,
)
from reg_agent.tools.duckdb_tool import DuckDBToolDeps

# Use Path for default DB location
DEFAULT_DB_DIR = Path("./db")
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "regulations.db"


# Load environment variables (especially for LLM config)
load_dotenv()

# Define DB Path using the default
DB_PATH = os.getenv("DB_PATH", str(DEFAULT_DB_PATH))
DB_DIR = Path(DB_PATH).parent
DB_DIR.mkdir(parents=True, exist_ok=True)  # Ensure directory exists

# Configure structured logging if not already done externally
# structlog.configure(...) # Add basic config if needed


async def run_pipeline(user_query: str, db_path: str = DB_PATH):
    """Runs the full Query -> CAG pipeline graph."""
    log.info("Starting Query-CAG pipeline run", query=user_query, db=db_path)

    # --- 1. Setup Dependencies --- #
    if not os.path.exists(db_path):
        log.error("Database file not found", path=db_path)
        print(f"Error: Database not found at {db_path}. Please run ingestion first.")
        return

    engine = create_engine(f"duckdb:///{db_path}")
    # Ensure models are known to SQLModel if run independently
    # from reg_agent.core.db import models # noqa
    # SQLModel.metadata.create_all(engine) # Usually not needed if DB exists

    graph_result = None  # Initialize to handle potential errors before assignment
    try:
        with Session(engine) as session:
            repo = DocumentRepository(session)
            deps = DuckDBToolDeps(repo=repo)

            # --- 2. Create Graph --- #
            graph = create_query_cag_graph()

            # --- 3. Define Initial State --- #
            initial_state = QueryAndCAGState(user_query=user_query, deps=deps)

            # --- 4. Run Graph --- #
            log.info("Executing graph...")
            # Pass initial_state AND the starting node instance to run method
            graph_result = await graph.run(
                QueryAgentNode(),  # Start with an instance of the first node
                state=initial_state,
            )
            log.info("Graph execution finished.")

            print("\n--- Final Output ---")
            # Access final output via the output attribute of the End node result
            if isinstance(graph_result, End):
                print(graph_result.output)
            elif (
                graph_result
                and hasattr(graph_result, "state")
                and graph_result.state
                and graph_result.state.final_output
            ):
                # Fallback if it somehow didn't end with End but has state
                log.warning(
                    "Graph finished but result was not End node",
                    result_type=type(graph_result),
                )
                print(graph_result.state.final_output)
            else:
                print("Graph did not produce a final output or ended unexpectedly.")
                # Optional: Log the graph_result for debugging
                # log.warning("Unexpected graph result", result=graph_result)

            # Optional: Print full state for debugging
            # print("\n--- Full State Dump ---")
            # if graph_result and hasattr(graph_result, 'state') and graph_result.state:
            #     print(graph_result.state.model_dump_json(indent=2))

    except Exception as e:
        log.exception("Pipeline execution failed", error=e)
        print(f"\nAn error occurred during pipeline execution: {e}")
    finally:
        if engine:
            engine.dispose()
            log.info("Database engine disposed.")


async def main():
    # --- Define Test Cases --- #
    test_queries = [
        "what docs do you have about?",
        "Find documents issued by the CFPB",
        "Find documents from NonExistentAgency",
        "Find Consent Orders issued by the CFPB",
        "Find documents from the Consumer Financial Protection Bureau",
        # Add more queries as needed
    ]

    log.info(f"Running {len(test_queries)} test queries...")
    for i, user_query in enumerate(test_queries):
        print(f"\n===== Running Test Case {i + 1}/{len(test_queries)} ====")
        log.info(f"Running test query: {user_query}")
        await run_pipeline(user_query)
        print(f"===== Finished Test Case {i + 1}/{len(test_queries)} ====")
        # Optional: Add a small delay if running many tests rapidly
        # await asyncio.sleep(1)

    log.info("All test queries finished.")


if __name__ == "__main__":
    print("Starting Test Query Runner for Query-CAG Pipeline.")
    # Uncomment and potentially refine Logfire setup if needed
    if os.environ.get("ENABLE_LOGFIRE", "false").lower() == "true":
        try:
            import logfire

            # Minimal config, adjust if needed
            logfire.configure()
            print("Logfire configured.")
        except ImportError:
            print("Logfire import failed, ensure installed if enabled.")
            log.warning("Logfire import failed, ensure installed if enabled.")
        except Exception as lf_err:
            print(f"Logfire configuration failed: {lf_err}")
            log.error("Logfire configuration failed", error=lf_err, exc_info=True)

    asyncio.run(main())
