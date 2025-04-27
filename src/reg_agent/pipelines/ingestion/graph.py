# src/reg_agent/pipelines/ingestion/graph.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pydantic_graph as pg
import structlog

# Assuming tasks might need access to the database or specific configurations
# We can define a context model passed to nodes
from reg_agent.core.db.connection import create_db_and_tables, get_engine

# Import the original task functions
from reg_agent.pipelines.ingestion.tasks.task_1_create_records import run_task_1
from reg_agent.pipelines.ingestion.tasks.task_2_ocr import run_task_2
# Import the task function and its result type
from reg_agent.pipelines.ingestion.tasks.task_3_metadata import (
    Task3Result,
    run_task_3,
)

log = structlog.get_logger()


# --- State Definition ---
@dataclass
class PipelineState:
    source_dir: Path
    db_file: Path
    # Store results from each task here
    task_1_results: Optional[Tuple[int, int, int]] = None
    task_2_results: Optional[Tuple[int, int, int, int]] = None
    task_3_results: Optional[Task3Result] = None
    final_summary: Dict[str, Any] = field(default_factory=dict)


# --- Node Definitions ---


@dataclass
class Task1CreateRecordsNode(pg.BaseNode[PipelineState]):
    """Node to execute Task 1: Create Records."""

    async def run(self, ctx: pg.GraphRunContext[PipelineState]) -> "Task2OcrNode":
        log.info(
            "Executing Task 1: Create Records", source_dir=str(ctx.state.source_dir)
        )
        inserted, skipped, errors = run_task_1(ctx.state.source_dir)
        log.info("Task 1 finished", inserted=inserted, skipped=skipped, errors=errors)
        ctx.state.task_1_results = (inserted, skipped, errors)
        # if errors > 0:
        #     log.warning("Task 1 encountered errors", count=errors)
        # Transition to Task 2
        return Task2OcrNode()


@dataclass
class Task2OcrNode(pg.BaseNode[PipelineState]):
    """Node to execute Task 2: OCR."""

    async def run(self, ctx: pg.GraphRunContext[PipelineState]) -> "Task3MetadataNode":
        log.info("Executing Task 2: OCR")
        found, success, skipped, errors = run_task_2()
        log.info(
            "Task 2 finished",
            found=found,
            success=success,
            skipped=skipped,
            errors=errors,
        )
        ctx.state.task_2_results = (found, success, skipped, errors)
        # if errors > 0:
        #     log.warning("Task 2 encountered errors", count=errors)
        # Transition to Task 3
        return Task3MetadataNode()


@dataclass
class Task3MetadataNode(pg.BaseNode[PipelineState]):
    """Node to execute Task 3: Metadata Extraction (Async)."""

    async def run(
        self, ctx: pg.GraphRunContext[PipelineState]
    ) -> "AggregateResultsNode":
        log.info("Executing Task 3: Metadata Extraction (async)")
        # Store the entire result dictionary
        task_3_result_dict: Task3Result = await run_task_3()
        log.info(
            "Task 3 finished",
            found=task_3_result_dict["found"],
            success=task_3_result_dict["success"],
            errors=task_3_result_dict["errors"],
            # Optionally log error details count or snippet here if needed
        )
        ctx.state.task_3_results = task_3_result_dict
        # if task_3_result_dict["errors"] > 0:
        #     log.warning("Task 3 encountered errors", count=task_3_result_dict["errors"])
        # Transition to Aggregation
        return AggregateResultsNode()


@dataclass
# Specify Output Type in BaseNode generic: Dict[str, Any]
class AggregateResultsNode(pg.BaseNode[PipelineState, None, Dict[str, Any]]):
    """Node to aggregate results from previous tasks."""

    # The run signature is now compatible with BaseNode
    async def run(
        self, ctx: pg.GraphRunContext[PipelineState]
    ) -> pg.End[Dict[str, Any]]:
        log.info("Aggregating pipeline results...")
        # Retrieve results stored in state
        t1_res = ctx.state.task_1_results or (0, 0, 0)
        t2_res = ctx.state.task_2_results or (0, 0, 0, 0)
        # Default Task 3 result if None
        t3_res_dict = ctx.state.task_3_results or {
            "found": 0, "success": 0, "errors": 0, "error_details": []
        }

        results = {
            "task_1": {
                "inserted": t1_res[0],
                "skipped": t1_res[1],
                "errors": t1_res[2],
            },
            "task_2": {
                "found": t2_res[0],
                "success": t2_res[1],
                "skipped": t2_res[2],
                "errors": t2_res[3],
            },
            "task_3": {
                "found": t3_res_dict["found"],
                "success": t3_res_dict["success"],
                "errors": t3_res_dict["errors"],
                "error_details": t3_res_dict["error_details"], # Include error details
            },
        }
        ctx.state.final_summary = results  # Store final summary in state too
        log.info("Pipeline results aggregated.", results=results)
        # Pass results positionally to pg.End
        return pg.End(results)


# --- Function to run the graph ---


async def execute_ingestion_graph(source_dir: Path, db_file: Path) -> Dict[str, Any]:
    """Initializes and runs the IngestionGraph."""
    log.info(
        "Initializing Ingestion Graph execution...",
        source_dir=str(source_dir),
        db_file=str(db_file),
    )

    # --- Database Setup (Perform before graph execution) ---
    try:
        engine = get_engine(db_file=db_file)
        create_db_and_tables(engine)
        log.info("Database setup complete.")
    except Exception as e:
        log.exception("Database setup failed. Halting execution.", error=str(e))
        return {"error": "Database setup failed", "details": str(e)}

    # --- Initialize State ---
    initial_state = PipelineState(source_dir=source_dir, db_file=db_file)

    # --- Define Graph Topology ---
    # Pass the node *types* to the Graph constructor
    ingestion_graph = pg.Graph(
        nodes=(
            Task1CreateRecordsNode,
            Task2OcrNode,
            Task3MetadataNode,
            AggregateResultsNode,
        )
    )

    try:
        log.info("Executing IngestionGraph...")
        # graph.run returns GraphRunResult, which contains state and output
        # Adjust type hint based on expected final state and output types
        run_result: pg.GraphRunResult[
            PipelineState, Dict[str, Any]
        ] = await ingestion_graph.run(Task1CreateRecordsNode(), state=initial_state)
        log.info("IngestionGraph execution finished.")

        # Extract the output from the GraphRunResult object
        final_output = run_result.output if run_result else {}
        # Access final state via run_result.state if needed
        return final_output if final_output is not None else {}

    except Exception as e:
        log.exception("An error occurred during graph execution.", error=str(e))
        return {"error": "Graph execution failed", "details": str(e)}
