# tests/agents/test_query_agent.py

import pytest
from unittest.mock import MagicMock, patch
import importlib # Add importlib for reloading
import uuid

# Pydantic AI Testing imports
from pydantic_ai import RunContext, capture_run_messages
from pydantic_ai.models import Usage
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import ToolCallPart, UserPromptPart

# Import the function to test and dependencies
from reg_agent.agents.query_agent import create_query_agent, query_agent # Also import instance
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
    # Ensure the real agent instance (created at module import) is used
    # We assume initialization succeeded based on previous tests
    global query_agent

    # Use TestModel to simulate LLM deciding to call the query tool
    # TestModel will automatically generate *some* args based on the tool schema
    test_model = TestModel()

    # Act
    with capture_run_messages() as messages:
        with query_agent.override(model=test_model):
            # We pass the *mocked* deps here
            await query_agent.run(user_prompt, deps=tool_deps)

    # Assert
    # Check that the message history contains a tool call part
    # Note: TestModel might not extract the exact filter from the prompt,
    # it mainly tests *that* the tool was chosen and called with valid types.
    found_tool_call = False
    for message in messages:
        if not message.parts: continue
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == 'query_metadata':
                found_tool_call = True
                # Check args are present and filters is a dict (TestModel generated)
                assert isinstance(part.args, dict)
                assert 'filters' in part.args
                assert isinstance(part.args['filters'], dict)
                # Optionally check if limit is None or a dict key if TestModel includes it
                # assert 'limit' not in part.args or part.args['limit'] is None
                break
        if found_tool_call: break

    assert found_tool_call, "query_metadata tool was not called"
    # Check that the *mocked* repository method was called by the tool
    # The tool function should call this when executed by the TestModel/Agent run
    mock_repo.find_by_metadata.assert_called_once()

# TODO: Add test using TestModel for explore_metadata call
# TODO: Add test using FunctionModel for more precise control over tool args/flow

# Remove previous test versions if they exist (or ensure file is replaced) 