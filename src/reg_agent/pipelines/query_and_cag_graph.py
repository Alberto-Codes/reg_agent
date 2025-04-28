# src/reg_agent/pipelines/query_and_cag_graph.py
"""Defines the Pydantic Graph for the Query -> CAG workflow using pydantic-graph."""

# Enable postponed evaluation of annotations (PEP 563)
from __future__ import annotations

import json  # Import json for parsing
import re  # Import re for regex
import uuid
from typing import Any, List, Optional

import structlog
from pydantic import BaseModel, ValidationError  # Import ValidationError

# Correct imports based on pydantic-graph documentation
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from reg_agent.agents.cag_agent import create_cag_agent
from reg_agent.agents.query_agent import QueryAgentResult as QueryAgentStructuredResult
from reg_agent.agents.query_agent import create_query_agent
from reg_agent.tools.duckdb_tool import DuckDBToolDeps

log = structlog.get_logger()


# --- State Model for the Graph --- #
class QueryAndCAGState(BaseModel):
    user_query: str
    deps: DuckDBToolDeps
    query_agent_result: Optional[QueryAgentStructuredResult] = None
    retrieved_doc_ids: Optional[List[uuid.UUID]] = None
    cag_agent_raw_output: Optional[str] = None
    final_output: Optional[str] = None
    error: Optional[str] = None
    model_config = {"arbitrary_types_allowed": True}


# --- Node Definitions --- #


class QueryAgentNode(BaseNode[QueryAndCAGState]):
    async def run(self, ctx: GraphRunContext[QueryAndCAGState]) -> ShouldRunCAGNode:
        state = ctx.state
        log.info("Running QueryAgentNode", user_query=state.user_query)
        if not state.deps:
            state.error = "Dependencies not found in state for QueryAgentNode"
            log.error(state.error)
            return ShouldRunCAGNode()

        try:
            query_agent = create_query_agent()
            result = await query_agent.run(state.user_query, deps=state.deps)
            raw_output_str = result.output

            if isinstance(raw_output_str, str):
                log.debug("QueryAgent returned a string, attempting extraction and parse.", raw_output_preview=raw_output_str[:200])
                json_str_to_parse = raw_output_str.strip()
                match = re.search(r"```(?:json)?\s*({.*?})\s*```", json_str_to_parse, re.DOTALL | re.IGNORECASE)
                if match:
                    json_str_to_parse = match.group(1).strip()
                    log.debug("Extracted JSON content from markdown block.", extracted_preview=json_str_to_parse[:200])

                try:
                    parsed_output = QueryAgentStructuredResult.model_validate_json(json_str_to_parse)
                    state.query_agent_result = parsed_output # Store parsed result

                    # --- Start: Post-Parsing Validation --- #
                    summary_lower = parsed_output.summary.lower()
                    ids_present = bool(parsed_output.retrieved_doc_ids)
                    found_indication = "found" in summary_lower and "no" not in summary_lower # Simple check

                    if ids_present and not found_indication:
                        if "error" not in summary_lower and "fail" not in summary_lower:
                            log.warning(
                                "Validation Mismatch: IDs present but summary doesn't indicate success.",
                                summary=parsed_output.summary,
                                ids_count=len(parsed_output.retrieved_doc_ids or []),
                            )
                            # Decide if this is critical enough to set state.error
                            # state.error = state.error or "QueryAgent summary inconsistent with document IDs."

                    elif not ids_present and found_indication:
                        # Check if it mentions *too many* results, which is valid for empty IDs
                        if "many" not in summary_lower and "limit" not in summary_lower:
                             log.warning(
                                "Validation Mismatch: No IDs present but summary indicates documents found.",
                                summary=parsed_output.summary,
                            )
                            # state.error = state.error or "QueryAgent summary inconsistent with lack of document IDs."

                    # If no critical validation mismatch, proceed with state update
                    if not state.error:
                         state.retrieved_doc_ids = parsed_output.retrieved_doc_ids
                         log.info("QueryAgent finished (JSON parsed & validated).", summary=parsed_output.summary, ids_found=len(state.retrieved_doc_ids or []))
                         if "error" in summary_lower or "failed" in summary_lower:
                             if not state.error:
                                 state.error = f"QueryAgent reported an issue in parsed summary: {parsed_output.summary}"
                                 log.warning(state.error)
                    else:
                        # If validation above set an error, ensure IDs are null
                        state.retrieved_doc_ids = None
                        log.warning("Post-parsing validation failed, clearing retrieved IDs.", summary=parsed_output.summary)
                    # --- End: Post-Parsing Validation --- #

                except (json.JSONDecodeError, ValidationError) as parse_err:
                    log.warning(
                        "Failed to parse/validate extracted QueryAgent output as JSON.",
                        error=str(parse_err),
                        attempted_json_string=json_str_to_parse[:500] + "..." if len(json_str_to_parse) > 500 else json_str_to_parse,
                        original_raw_output=raw_output_str[:500] + "..." if len(raw_output_str) > 500 else raw_output_str,
                    )
                    state.retrieved_doc_ids = None
                    state.query_agent_result = None # Ensure no partial result is stored
                    state.error = state.error or f"QueryAgent returned unparsable/invalid JSON: {raw_output_str[:100]}..."
            elif isinstance(raw_output_str, QueryAgentStructuredResult):
                # Original logic (shouldn't be hit if output_type is commented out)
                log.info("QueryAgent returned structured output directly.")
                state.query_agent_result = raw_output_str
                state.retrieved_doc_ids = raw_output_str.retrieved_doc_ids
                log.info("QueryAgent finished.", summary=raw_output_str.summary, ids_found=len(state.retrieved_doc_ids or []))
                if "error" in raw_output_str.summary.lower() or "failed" in raw_output_str.summary.lower():
                     if not state.error:
                         state.error = f"QueryAgent reported an issue: {raw_output_str.summary}"
                         log.warning(state.error)
            else:
                log.warning("QueryAgent output was neither string nor QueryAgentResult model", output_type=type(raw_output_str))
                state.retrieved_doc_ids = None
                state.query_agent_result = None
                state.error = state.error or "QueryAgent returned unexpected output type."

        except Exception as e:
            log.exception("Error running QueryAgent", exc_info=True)
            state.error = f"QueryAgent execution failed: {e}"
            # Ensure state reflects failure
            state.query_agent_result = None
            state.retrieved_doc_ids = None

        return ShouldRunCAGNode()


class ShouldRunCAGNode(BaseNode[QueryAndCAGState]):
    async def run(
        self, ctx: GraphRunContext[QueryAndCAGState]
    ) -> CAGAgentNode | FormatOutputNode:
        state = ctx.state
        log.info(
            "Running ShouldRunCAGNode Check",
            has_ids=bool(state.retrieved_doc_ids),
            has_error=bool(state.error),
        )
        if state.error is None and state.retrieved_doc_ids:
            log.debug("Routing to CAGAgentNode")
            return CAGAgentNode()  # Proceed to CAG if no error and IDs found
        else:
            log.debug("Routing to FormatOutputNode (error or no IDs)")
            return FormatOutputNode()  # Skip CAG if error or no IDs


class CAGAgentNode(BaseNode[QueryAndCAGState]):
    async def run(self, ctx: GraphRunContext[QueryAndCAGState]) -> "FormatOutputNode":
        state = ctx.state
        log.info("Running CAGAgentNode", doc_ids=state.retrieved_doc_ids)
        # Basic checks (should be guaranteed by ShouldRunCAGNode routing, but belt-and-suspenders)
        if not state.deps or not state.retrieved_doc_ids:
            state.error = (
                state.error or "Internal error: CAG node reached in invalid state"
            )
            log.error(
                state.error,
                has_deps=bool(state.deps),
                has_ids=bool(state.retrieved_doc_ids),
            )
            return FormatOutputNode()  # Go to format node to report error

        try:
            cag_agent = create_cag_agent()
            cag_prompt = f"User Query: {state.user_query}\nDocument IDs: {[str(id) for id in state.retrieved_doc_ids]}\nPlease fetch the text for these IDs and answer the query based *only* on their content."
            log.debug(
                "Running CAG agent with prompt", prompt_snippet=cag_prompt[:200] + "..."
            )
            result = await cag_agent.run(cag_prompt, deps=state.deps)
            state.cag_agent_raw_output = result.output
            log.info("CAGAgent finished.")
        except Exception as e:
            log.exception("Error running CAGAgent", exc_info=True)
            state.error = state.error or f"CAGAgent failed: {e}"

        # Always transition to format node after CAG attempt
        return FormatOutputNode()


class FormatOutputNode(BaseNode[QueryAndCAGState]):
    async def run(self, ctx: GraphRunContext[QueryAndCAGState]) -> End[Any]:
        state = ctx.state
        log.info("Running FormatOutputNode")
        if state.error:
            state.final_output = f"Error during processing: {state.error}"
        elif state.cag_agent_raw_output:
            state.final_output = state.cag_agent_raw_output
        elif state.query_agent_result and state.query_agent_result.summary:
            # Now accesses summary from the parsed result
            state.final_output = state.query_agent_result.summary
        else:
            state.final_output = (
                "Processing finished, but no specific result was generated."
            )
        log.info("Formatted final output", output_length=len(state.final_output or ""))

        final_output = (
            state.final_output
            if state.final_output is not None
            else "No output generated."
        )
        return End(final_output)


# --- Graph Definition --- #
def create_query_cag_graph() -> Graph[QueryAndCAGState]:
    """Creates the Query -> CAG Pydantic Graph."""
    # Graph initialized with node classes and state type
    graph = Graph[QueryAndCAGState](
        nodes=(
            QueryAgentNode,
            ShouldRunCAGNode,
            CAGAgentNode,
            FormatOutputNode,
        ),
        state_type=QueryAndCAGState,
    )
    log.info("Query-CAG graph created using pydantic-graph API.")
    return graph

    # Example usage:
    # async def main():
    #     # 1. Setup Dependencies (e.g., Session, Repository)
    #     # from sqlmodel import create_engine, Session
    #     # from reg_agent.core.db.repositories import DocumentRepository
    #     # engine = create_engine("duckdb:///path/to/your/db.db")
    #     # with Session(engine) as session:
    #     #     repo = DocumentRepository(session)
    #     #     deps = DuckDBToolDeps(repo=repo)
    #     #
    #     #     # 2. Create Graph
    #     #     graph = create_query_cag_graph()
    #     #
    #     #     # 3. Define Initial State
    #     #     user_input = "find ids for cfpb cases"
    #     #     initial_state = QueryAndCAGState(user_query=user_input, deps=deps)
    #     #
    #     #     # 4. Run Graph
    #     #     final_state = await graph.run(initial_state)
    #     #
    #     #     # 5. Get Output
    #     #     print("--- Final Output ---")
    #     #     print(final_state.final_output)
    #     #     print("--- Full State ---")
    #     #     print(final_state.model_dump_json(indent=2))
    #
    # if __name__ == "__main__":
    #     # asyncio.run(main())
    pass  # Avoid running example directly
