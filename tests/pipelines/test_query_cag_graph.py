import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_graph import GraphRunContext

from reg_agent.agents.query_agent import QueryAgentResult as QueryAgentStructuredResult
from reg_agent.pipelines.query_and_cag_graph import (
    QueryAgentNode,
    QueryAndCAGState,
    ShouldRunCAGNode,
    CAGAgentNode,  # Import needed nodes
    FormatOutputNode,  # Import needed nodes
    # Import other nodes as needed for future tests
)
from reg_agent.tools.duckdb_tool import DuckDBToolDeps

# Mark all tests in this module to be run with asyncio
pytestmark = pytest.mark.anyio

# --- Fixtures and Mocks ---


@pytest.fixture
def mock_duckdb_deps(mocker: Any) -> DuckDBToolDeps:
    """Fixture to create mocked DuckDBToolDeps."""
    mock_repo = mocker.MagicMock()  # Mock the repository within deps
    return DuckDBToolDeps(repo=mock_repo)


@pytest.fixture
def mock_query_agent(mocker: Any) -> MagicMock:
    """Fixture to mock the QueryAgent instance and its run method."""
    mock_agent = mocker.MagicMock()
    # Configure the run method to be an AsyncMock
    mock_agent.run = mocker.AsyncMock()
    return mock_agent


@pytest.fixture
def mock_cag_agent(mocker: Any) -> MagicMock:
    """Fixture to mock the CAGAgent instance and its run method."""
    mock_agent = mocker.MagicMock()
    mock_agent.run = mocker.AsyncMock()
    return mock_agent


@pytest.fixture(autouse=True)
def patch_agent_creators(
    mocker: Any, mock_query_agent: MagicMock, mock_cag_agent: MagicMock
) -> None:
    """Automatically patch the agent creation functions for all tests in this module."""
    # Patch create_query_agent to return our mock
    mocker.patch(
        "reg_agent.pipelines.query_and_cag_graph.create_query_agent",
        return_value=mock_query_agent,
    )
    # Patch create_cag_agent
    mocker.patch(
        "reg_agent.pipelines.query_and_cag_graph.create_cag_agent",
        return_value=mock_cag_agent,
    )


# --- Test Cases ---


async def test_query_agent_node_success_with_ids(
    mock_query_agent: MagicMock,
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test QueryAgentNode when the agent successfully returns document IDs."""
    # --- Arrange ---
    node = QueryAgentNode()
    user_query = "test query for documents"
    doc_id_1 = uuid.uuid4()
    doc_id_2 = uuid.uuid4()

    mock_agent_output = QueryAgentStructuredResult(
        summary="Found 2 documents.",
        retrieved_doc_ids=[doc_id_1, doc_id_2],
    )
    mock_query_agent.run.return_value = MagicMock(
        output=mock_agent_output.model_dump_json()
    )

    initial_state = QueryAndCAGState(user_query=user_query, deps=mock_duckdb_deps)
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    mock_query_agent.run.assert_awaited_once_with(user_query, deps=mock_duckdb_deps)
    assert ctx.state.error is None
    assert ctx.state.query_agent_result == mock_agent_output
    assert ctx.state.retrieved_doc_ids == [doc_id_1, doc_id_2]
    assert isinstance(next_node, ShouldRunCAGNode)


async def test_query_agent_node_success_no_ids(
    mock_query_agent: MagicMock,
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test QueryAgentNode when the agent successfully finds no document IDs."""
    # --- Arrange ---
    node = QueryAgentNode()
    user_query = "test query, no results expected"

    mock_agent_output = QueryAgentStructuredResult(
        summary="No documents found matching the criteria.",
        retrieved_doc_ids=None,
    )
    mock_query_agent.run.return_value = MagicMock(
        output=mock_agent_output.model_dump_json()
    )

    initial_state = QueryAndCAGState(user_query=user_query, deps=mock_duckdb_deps)
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    mock_query_agent.run.assert_awaited_once_with(user_query, deps=mock_duckdb_deps)
    assert ctx.state.error is None
    assert ctx.state.query_agent_result == mock_agent_output
    assert ctx.state.retrieved_doc_ids is None
    assert isinstance(next_node, ShouldRunCAGNode)


async def test_query_agent_node_agent_error(
    mock_query_agent: MagicMock,
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test QueryAgentNode when the agent's run method raises an exception."""
    # --- Arrange ---
    node = QueryAgentNode()
    user_query = "query that causes agent error"
    agent_error_message = "LLM connection failed"
    mock_query_agent.run.side_effect = Exception(agent_error_message)

    initial_state = QueryAndCAGState(user_query=user_query, deps=mock_duckdb_deps)
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    mock_query_agent.run.assert_awaited_once_with(user_query, deps=mock_duckdb_deps)
    assert ctx.state.error is not None
    assert agent_error_message in ctx.state.error
    assert ctx.state.query_agent_result is None
    assert ctx.state.retrieved_doc_ids is None
    assert isinstance(next_node, ShouldRunCAGNode)


async def test_query_agent_node_unparsable_output(
    mock_query_agent: MagicMock,
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test QueryAgentNode when the agent returns unparsable non-JSON output."""
    # --- Arrange ---
    node = QueryAgentNode()
    user_query = "query leading to bad output"
    bad_output = "Sorry, I cannot fulfill this request right now."
    mock_query_agent.run.return_value = MagicMock(output=bad_output)

    initial_state = QueryAndCAGState(user_query=user_query, deps=mock_duckdb_deps)
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    mock_query_agent.run.assert_awaited_once_with(user_query, deps=mock_duckdb_deps)
    assert ctx.state.error is not None
    assert "unparsable/invalid JSON" in ctx.state.error
    assert ctx.state.query_agent_result is None
    assert ctx.state.retrieved_doc_ids is None
    assert isinstance(next_node, ShouldRunCAGNode)


# --- Tests for ShouldRunCAGNode ---


async def test_should_run_cag_node_routes_to_cag(
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test ShouldRunCAGNode routes to CAGAgentNode when no error and IDs exist."""
    # --- Arrange ---
    node = ShouldRunCAGNode()
    doc_id = uuid.uuid4()
    initial_state = QueryAndCAGState(
        user_query="test",
        deps=mock_duckdb_deps,
        retrieved_doc_ids=[doc_id],  # Has IDs
        error=None,  # No error
    )
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    assert isinstance(next_node, CAGAgentNode)


async def test_should_run_cag_node_routes_to_format_on_error(
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test ShouldRunCAGNode routes to FormatOutputNode when an error exists."""
    # --- Arrange ---
    node = ShouldRunCAGNode()
    doc_id = uuid.uuid4()
    initial_state = QueryAndCAGState(
        user_query="test",
        deps=mock_duckdb_deps,
        retrieved_doc_ids=[doc_id],  # Has IDs (doesn't matter)
        error="Something went wrong",  # Has error
    )
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    assert isinstance(next_node, FormatOutputNode)


async def test_should_run_cag_node_routes_to_format_no_ids(
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test ShouldRunCAGNode routes to FormatOutputNode when no IDs exist."""
    # --- Arrange ---
    node = ShouldRunCAGNode()
    initial_state = QueryAndCAGState(
        user_query="test",
        deps=mock_duckdb_deps,
        retrieved_doc_ids=None,  # No IDs
        error=None,  # No error
    )
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    assert isinstance(next_node, FormatOutputNode)


# --- Tests for CAGAgentNode ---


async def test_cag_agent_node_success(
    mock_cag_agent: MagicMock,  # Use the mock CAG agent fixture
    mock_duckdb_deps: DuckDBToolDeps,
):
    """Test CAGAgentNode successful execution."""
    # --- Arrange ---
    node = CAGAgentNode()
    user_query = "Summarize these documents"
    doc_id_1 = uuid.uuid4()
    expected_cag_output = "This is the summary based on the documents."

    # Configure mock CAG agent to return a successful output
    mock_cag_agent.run.return_value = MagicMock(output=expected_cag_output)

    # Prepare initial state (assuming QueryAgentNode ran successfully)
    initial_state = QueryAndCAGState(
        user_query=user_query,
        deps=mock_duckdb_deps,
        retrieved_doc_ids=[doc_id_1],
        error=None,
    )
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    # Check CAG agent was called correctly
    doc_id_str = str(doc_id_1)
    expected_prompt = f"User Query: {user_query}\nDocument IDs: {[doc_id_str]}\nPlease fetch the text for these IDs and answer the query based *only* on their content."
    mock_cag_agent.run.assert_awaited_once_with(expected_prompt, deps=mock_duckdb_deps)

    # Check state updates (directly on ctx.state)
    assert ctx.state.error is None
    assert ctx.state.cag_agent_raw_output == expected_cag_output

    # Check routing
    assert isinstance(next_node, FormatOutputNode)


async def test_cag_agent_node_agent_error(
    mock_cag_agent: MagicMock, mock_duckdb_deps: DuckDBToolDeps
):
    """Test CAGAgentNode handles agent errors."""
    # --- Arrange ---
    node = CAGAgentNode()
    user_query = "test"
    doc_id_1 = uuid.uuid4()
    error_message = "Agent failed"
    mock_cag_agent.run.side_effect = Exception(error_message)

    # Use a consistent UUID for reproducible prompt string
    doc_id_str = str(doc_id_1)

    initial_state = QueryAndCAGState(
        user_query=user_query,
        deps=mock_duckdb_deps,
        retrieved_doc_ids=[doc_id_1],
        error=None,
        # final_report=None, # Remove - not a field in QueryAndCAGState
    )
    ctx = GraphRunContext[QueryAndCAGState](state=initial_state, deps=mock_duckdb_deps)

    # --- Act ---
    next_node = await node.run(ctx)

    # --- Assert ---
    # Check CAG agent was called correctly with the generated prompt
    expected_prompt = f"User Query: {user_query}\nDocument IDs: {[doc_id_str]}\nPlease fetch the text for these IDs and answer the query based *only* on their content."
    mock_cag_agent.run.assert_awaited_once_with(expected_prompt, deps=mock_duckdb_deps)

    # Check routing
    assert isinstance(next_node, FormatOutputNode)

    # Check state updates (directly on ctx.state)
    assert ctx.state.error == f"CAGAgent failed: {error_message}"
    assert ctx.state.cag_agent_raw_output is None # Should be None on error


# TODO: Add tests for FormatOutputNode
