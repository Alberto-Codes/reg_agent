# scripts/run_tool_test.py # Renamed from test_duckdb_tool.py

import asyncio
import sys
from pathlib import Path

import structlog
from pydantic_ai import RunContext
from pydantic_ai.models import Usage
from sqlmodel import Session



from reg_agent.core.db.connection import get_engine
from reg_agent.core.db.repositories import DocumentRepository
from reg_agent.tools.duckdb_tool import (
    DuckDBToolDeps,
    ExploreMetadataInput,
    QueryMetadataInput,
    explore_metadata,
    query_metadata,
)

log = structlog.get_logger()

# Define project root relative to the script location
project_root = Path(__file__).parent.parent

async def main():
    # --- Database Setup ---
    db_dir = project_root / "db"
    db_file = db_dir / "regulations.db"
    db_dir.mkdir(exist_ok=True)
    log.info("Connecting to database", db_path=str(db_file))
    if not db_file.exists():
        log.error("Database file not found.", db_path=str(db_file))
        sys.exit(1)
    engine = get_engine(db_file=db_file)

    with Session(engine) as session:
        repository = DocumentRepository(session=session)
        log.info("Repository initialized.")

        # --- Prepare Tool Context/Dependencies ---
        deps = DuckDBToolDeps(repo=repository)
        # Create a dummy RunContext with minimal required args
        # Initialize Usage without arguments, assuming defaults
        dummy_usage = Usage()
        ctx = RunContext(deps=deps, model=None, usage=dummy_usage, prompt=None)

        # --- Test explore_metadata (get all fields) ---
        print("\n--- Testing explore_metadata (all fields) ---")
        explore_input_all = ExploreMetadataInput()
        explore_output_all = await explore_metadata(ctx, explore_input_all)
        print(f"Input: {explore_input_all}")
        print(f"Output: {explore_output_all}")

        # --- Test explore_metadata (get distinct values for 'issuing_agency') ---
        print(
            "\n--- Testing explore_metadata (distinct values for 'issuing_agency') ---"
        )
        explore_input_distinct = ExploreMetadataInput(field="issuing_agency")
        explore_output_distinct = await explore_metadata(ctx, explore_input_distinct)
        print(f"Input: {explore_input_distinct}")
        print(f"Output: {explore_output_distinct}")

        # --- Test query_metadata (find specific document) ---
        print("\n--- Testing query_metadata --- ")
        # Use an identifier known from previous db inspection
        query_input = QueryMetadataInput(
            filters={"document_identifier": "2016-CFPB-0013"}
        )
        query_output = await query_metadata(ctx, query_input)
        print(f"Input: {query_input}")
        print(f"Output: {query_output}")

        # --- Test query_metadata (no matches) ---
        print("\n--- Testing query_metadata (no matches) --- ")
        query_input_none = QueryMetadataInput(
            filters={"document_type": "NonExistentType"}
        )
        query_output_none = await query_metadata(ctx, query_input_none)
        print(f"Input: {query_input_none}")
        print(f"Output: {query_output_none}")

    log.info("Tool test script finished.")


if __name__ == "__main__":
    asyncio.run(main())
