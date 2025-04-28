"""
Runtime/integration tests for the QueryAgent using TestModel.
"""

import asyncio
import sys
from pathlib import Path
import pytest
# from pydantic_ai.testing import TestModel, ToolCallLog # Old incorrect import
from pydantic_ai.models.test import TestModel # Correct import
# from pydantic_ai.testing import ToolCallLog # No longer needed
from pydantic_ai import capture_run_messages, models # Import capture_run_messages and models
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, TextPart, UserPromptPart, ModelMessage # Import message types and UserPromptPart, ModelMessage
import uuid # Import uuid
from unittest.mock import MagicMock # Import MagicMock

# Add src directory to sys.path for imports
# project_root = Path(__file__).resolve().parents[2] # tests/agents -> root
# sys.path.insert(0, str(project_root)) # Remove path manipulation

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool # For in-memory SQLite
from reg_agent.core.db.models import FileRecord # Corrected path
from reg_agent.core.db.repositories import DocumentRepository # Corrected path
from reg_agent.agents.query_agent import create_query_agent
from reg_agent.tools.duckdb_tool import ExploreMetadataOutput, DuckDBToolDeps # Added import for DuckDBToolDeps

# Import agent and dependencies
# from reg_agent.agents.query_agent import DuckDBToolDeps # Removed duplicate
# Removed old commented-out import attempts

from pydantic_ai.models.function import FunctionModel, AgentInfo # Import FunctionModel and AgentInfo

# Remove the db_setup fixture as we will mock the repo
# @pytest.fixture(scope="function")
# def db_setup():
#     """Sets up an in-memory DuckDB engine and creates tables."""
#     engine = create_engine("duckdb:///:memory:") 
#     
#     # Ensure tables are created
#     SQLModel.metadata.create_all(engine) 
#     
#     yield engine # Yield only the engine
# 
#     # Teardown (if necessary, e.g., drop tables or close engine explicitly)
#     # For in-memory, it might not be strictly needed, but good practice:
#     # SQLModel.metadata.drop_all(engine)
#     # engine.dispose() # Close connections

# --- Mock LLM function for FunctionModel ---
FINAL_OUTPUT_TEXT_EXPLORE = "Okay, here are the queryable metadata fields: issuing_agency, topic, year."

def mock_llm_explore_flow(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Simulates the LLM flow for the explore_metadata test."""
    last_request = messages[-1]
    if not isinstance(last_request, ModelRequest):
        # Should always end with a request in this flow
        raise ValueError("Unexpected message sequence for FunctionModel")

    # First turn: User prompt -> LLM calls explore_metadata
    if len(messages) == 1 and isinstance(last_request.parts[0], UserPromptPart):
        return ModelResponse(parts=[ToolCallPart(tool_name="explore_metadata", args={})])
    
    # Second turn: Tool return for explore_metadata -> LLM gives final text
    elif len(messages) == 3 and isinstance(last_request.parts[0], ToolReturnPart):
        if last_request.parts[0].tool_name == "explore_metadata":
             # We don't need to check the content of the tool return here,
             # as the Agent passes it to the FunctionModel.
             # We just simulate the LLM producing the final text response.
            return ModelResponse(parts=[TextPart(FINAL_OUTPUT_TEXT_EXPLORE)])
        else:
             raise ValueError(f"Unexpected tool return in FunctionModel: {last_request.parts[0].tool_name}")

    # Default / Error case
    raise ValueError(f"Unexpected message state in FunctionModel: {messages}")


@pytest.mark.asyncio
# Remove db_setup fixture from test signature
async def test_agent_explore_metadata_flow(): 
    """Test the agent flow when the 'explore_metadata' tool is invoked, mocking the repository."""
    # _engine = db_setup # Removed

    # --- Test Setup --- 
    # 1. Mock the Repository 
    mock_repo = MagicMock(spec=DocumentRepository)
    expected_fields = sorted(["issuing_agency", "topic", "year"])
    # Configure the mock method called by the tool
    # Note: The tool calls repo.get_queryable_fields via asyncio.to_thread,
    # so we mock the return value directly, not making it an async mock.
    mock_repo.get_queryable_fields.return_value = expected_fields

    # 2. Create the tool dependency with the mock repo
    tool_dependency = DuckDBToolDeps(repo=mock_repo)

    # 3. Create FunctionModel using the mock LLM function
    # The output returned by the *actual* tool function execution
    expected_tool_output = ExploreMetadataOutput(
        queryable_fields=expected_fields, # Expect success now due to mock
        distinct_values=None,
        error=None 
    )
    test_llm = FunctionModel(mock_llm_explore_flow)

    # 4. Create Agent with FunctionModel 
    agent_instance = create_query_agent(llm=test_llm)

    # --- Agent Run --- 
    # Use capture_run_messages to verify the full flow
    with capture_run_messages() as messages:
        # Pass mocked dependency wrapped in DuckDBToolDeps
        result = await agent_instance.run("What metadata fields can I query?", deps=tool_dependency)

    # --- Assertions --- 
    # 1. Assert the final output matches the text from FunctionModel
    assert result.output == FINAL_OUTPUT_TEXT_EXPLORE

    # 2. Assert the captured messages structure
    assert len(messages) == 4 # Request -> ToolCall -> ToolReturn -> Final Response
    # Initial request (UserPromptPart)
    assert isinstance(messages[0], ModelRequest)
    assert isinstance(messages[0].parts[0], UserPromptPart)
    assert messages[0].parts[0].content == "What metadata fields can I query?"
    
    # First response (ToolCallPart for explore_metadata)
    assert isinstance(messages[1], ModelResponse)
    assert len(messages[1].parts) == 1
    assert isinstance(messages[1].parts[0], ToolCallPart)
    assert messages[1].parts[0].tool_name == "explore_metadata"
    assert messages[1].parts[0].args == {}

    # Second request (ToolReturnPart for explore_metadata)
    assert isinstance(messages[2], ModelRequest)
    assert len(messages[2].parts) == 1
    assert isinstance(messages[2].parts[0], ToolReturnPart)
    assert messages[2].parts[0].tool_name == "explore_metadata"
    
    # Get the actual content returned by the tool (which used the mock repo)
    actual_tool_content = messages[2].parts[0].content
            
    # Check the *content* of the tool return matches the expected successful output
    assert actual_tool_content == expected_tool_output
    
    # Check the specific fields attribute matches the success expectation (sorted list)
    assert actual_tool_content.queryable_fields == expected_fields

    # Final response (TextPart)
    assert isinstance(messages[3], ModelResponse)
    assert len(messages[3].parts) == 1
    assert isinstance(messages[3].parts[0], TextPart)
    assert messages[3].parts[0].content == FINAL_OUTPUT_TEXT_EXPLORE
    
    # Assert that the mock repository method was called by the tool function
    mock_repo.get_queryable_fields.assert_called_once()

# More tests will be added below 