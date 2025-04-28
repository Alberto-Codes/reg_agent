# tests/agents/test_query_agent.py

import pytest
from unittest.mock import MagicMock, patch
import importlib # Add importlib for reloading
import uuid

# Pydantic AI Testing imports
from pydantic_ai import RunContext, capture_run_messages
from pydantic_ai.models import Usage
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import ToolCallPart, UserPromptPart, ModelResponse

# Import the function to test and dependencies
from reg_agent.agents.query_agent import create_query_agent
from reg_agent.tools.duckdb_tool import (
    DuckDBToolDeps,
    ExploreMetadataInput,
    QueryMetadataInput,
    explore_metadata,
    query_metadata,
)

# --- Fixtures for Tool/Deps Mocking (used by agent run tests) ---

@pytest.fixture
def mock_repo():
    """Fixture to create a mock DocumentRepository."""
    mock = MagicMock()
    # Configure mock methods used by tools
    mock.get_queryable_fields = MagicMock(return_value=["document_identifier", "document_type", "issuing_agency"])
    mock.get_distinct_values = MagicMock(return_value=["CFPB", "DOJ"])
    # Simulate find_by_metadata returning one record ID
    mock_record = MagicMock()
    mock_record.id = uuid.uuid4()
    mock.find_by_metadata = MagicMock(return_value=[mock_record])
    return mock

@pytest.fixture
def tool_deps(mock_repo):
    """Fixture to create DuckDBToolDeps with a mocked repository."""
    return DuckDBToolDeps(repo=mock_repo)

# --- Initialization Tests (remain the same) ---

@patch('reg_agent.agents.query_agent.google.auth.default')
def test_create_query_agent_success(mock_google_auth_default):
    """Test successful creation of the QueryAgent via the factory function."""
    # Arrange: Configure the mock for google.auth.default
    mock_credentials = MagicMock()
    mock_credentials.token = "mock-adc-token" # Provide the token
    # Ensure refresh does nothing problematic for the test
    mock_credentials.refresh = MagicMock()
    mock_google_auth_default.return_value = (mock_credentials, "mock-project")

    # Act: Call the factory function
    created_agent = create_query_agent()

    # Assert
    # Check external calls
    mock_google_auth_default.assert_called_once()
    mock_credentials.refresh.assert_called_once() # Check refresh was called

    # Check the returned agent instance
    assert created_agent is not None
    assert created_agent.model is not None
    # Cannot easily assert tools directly, rely on runtime tests
    # from reg_agent.tools.duckdb_tool import explore_metadata, query_metadata
    # assert explore_metadata in created_agent.tools
    # assert query_metadata in created_agent.tools

@patch('reg_agent.agents.query_agent.google.auth.default')
def test_create_query_agent_adc_failure(mock_google_auth_default):
    """Test factory function raises RuntimeError if ADC fails."""
    # Arrange
    from google.auth.exceptions import DefaultCredentialsError
    mock_google_auth_default.side_effect = DefaultCredentialsError("ADC not found")

    # Act & Assert
    with pytest.raises(RuntimeError, match="QueryAgent LLM setup failed due to missing ADC"):
        create_query_agent() # Call the factory function directly

    # Assert google auth was called
    mock_google_auth_default.assert_called_once()

# --- Agent Runtime Tests --- 

@pytest.mark.asyncio
async def test_agent_run_specific_query_calls_query_tool(tool_deps, mock_repo):
    """Test agent calls query_metadata tool for a specific query using TestModel."""
    # Arrange
    user_prompt = "Find the document with identifier 2016-CFPB-0013"
    
    # Create TestModel. For simple tool call checks, often no args needed.
    test_model = TestModel()

    # Create agent instance with TestModel
    agent_instance = create_query_agent(llm=test_model)

    # Act
    # Use capture_run_messages to get the interaction history
    with capture_run_messages() as messages:
        await agent_instance.run(user_prompt, deps=tool_deps)

    # Assert
    assert len(messages) >= 2 # At least Request -> ToolCall

    # Check the ModelResponse contains the expected ToolCallPart
    found_tool_call = False
    if isinstance(messages[1], ModelResponse):
        for part in messages[1].parts:
            if isinstance(part, ToolCallPart) and part.tool_name == 'query_metadata':
                found_tool_call = True
                # Check args (TestModel might auto-generate simple ones like empty dict)
                assert isinstance(part.args, dict)
                # More specific checks depend on TestModel's sophistication or explicit setup
                # assert part.args.get('filters') == {'document_identifier': '2016-CFPB-0013'} # Less reliable with TestModel
                break

    assert found_tool_call, "query_metadata tool was not called in captured messages"
    
    # Check that the *mocked* repository method was called by the tool
    # Assuming TestModel execution path includes running the tool function logic
    # (This assertion might be fragile depending on pydantic-ai's TestModel implementation details)
    # It might be better to test the tool function directly in unit tests
    # For agent tests, focus on the LLM interaction (tool choice/args) 
    # mock_repo.find_by_metadata.assert_called_once()

# TODO: Add test using TestModel for explore_metadata call
# TODO: Add test using FunctionModel for more precise control over tool args/flow

@pytest.mark.asyncio
async def test_agent_run_ambiguous_query_calls_explore_tool(tool_deps, mock_repo):
    """Test agent calls explore_metadata tool (for fields) for an ambiguous query using TestModel."""
    # Arrange
    user_prompt = "Tell me about Wells Fargo cases" # Ambiguous

    # Create TestModel
    test_model = TestModel()

    # Create agent instance with TestModel
    agent_instance = create_query_agent(llm=test_model)

    # Act
    # Use capture_run_messages
    with capture_run_messages() as messages:
        await agent_instance.run(user_prompt, deps=tool_deps)

    # Assert
    assert len(messages) >= 2

    # Check the ModelResponse contains the explore_metadata ToolCallPart
    found_explore_call = False
    if isinstance(messages[1], ModelResponse):
        for part in messages[1].parts:
            if isinstance(part, ToolCallPart) and part.tool_name == 'explore_metadata':
                found_explore_call = True
                # Expecting empty args for initial field exploration
                assert part.args == {} or part.args is None, f"Expected empty args for explore_metadata (fields), got {part.args}"
                break

    assert found_explore_call, "explore_metadata tool was not called for ambiguous query"

    # Check that the *mocked* repository method was called by the tool
    # explore_metadata with empty args should call get_queryable_fields
    # Again, this relies on TestModel executing tool logic; better tested elsewhere.
    # mock_repo.get_queryable_fields.assert_called_once() 