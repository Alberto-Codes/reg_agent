# tests/tools/test_duckdb_tool.py

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Usage

from reg_agent.tools.duckdb_tool import (
    DuckDBToolDeps,
    ExploreMetadataInput,
    ExploreMetadataOutput,
    QueryMetadataInput,
    QueryMetadataOutput,
    explore_metadata,
    query_metadata,
)

# --- Fixtures ---


@pytest.fixture
def mock_repo():
    """Fixture to create a mock DocumentRepository."""
    # Use AsyncMock for methods expected to be awaited with asyncio.to_thread
    mock = MagicMock()
    mock.get_queryable_fields = MagicMock()  # Sync method called via to_thread
    mock.get_distinct_values = MagicMock()  # Sync method called via to_thread
    mock.find_by_metadata = MagicMock()  # Sync method called via to_thread
    return mock


@pytest.fixture
def tool_deps(mock_repo):  # Depend on mock_repo fixture
    """Fixture to create DuckDBToolDeps with a mocked repository."""
    return DuckDBToolDeps(repo=mock_repo)


@pytest.fixture
def run_context(tool_deps):  # Depend on tool_deps fixture
    """Fixture to create a dummy RunContext with mocked dependencies."""
    dummy_usage = Usage()
    # Provide dummy model and prompt as required by RunContext constructor
    return RunContext(deps=tool_deps, model=None, usage=dummy_usage, prompt=None)


# --- Tests for explore_metadata ---


@pytest.mark.asyncio
async def test_explore_metadata_get_all_fields_success(run_context, mock_repo):
    """Test explore_metadata successfully returns all queryable fields."""
    # Arrange
    expected_fields = ["field1", "field2", "field3"]
    mock_repo.get_queryable_fields.return_value = expected_fields
    input_params = ExploreMetadataInput(field=None)  # No specific field requested

    # Act
    result = await explore_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, ExploreMetadataOutput)
    assert result.queryable_fields == expected_fields
    assert result.distinct_values is None
    assert result.error is None
    mock_repo.get_queryable_fields.assert_called_once()
    mock_repo.get_distinct_values.assert_not_called()


@pytest.mark.asyncio
async def test_explore_metadata_get_distinct_values_success(run_context, mock_repo):
    """Test explore_metadata successfully returns distinct values for a specific field."""
    # Arrange
    field_name = "issuing_agency"
    expected_values = ["CFPB", "SEC"]
    mock_repo.get_distinct_values.return_value = expected_values
    input_params = ExploreMetadataInput(field=field_name)

    # Act
    result = await explore_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, ExploreMetadataOutput)
    assert result.distinct_values == expected_values
    assert result.queryable_fields is None
    assert result.error is None
    mock_repo.get_distinct_values.assert_called_once_with(field_name)
    mock_repo.get_queryable_fields.assert_not_called()


@pytest.mark.asyncio
async def test_explore_metadata_get_all_fields_error(run_context, mock_repo):
    """Test explore_metadata handles errors when getting all fields."""
    # Arrange
    error_message = "Database connection failed"
    mock_repo.get_queryable_fields.side_effect = Exception(error_message)
    input_params = ExploreMetadataInput(field=None)

    # Act
    result = await explore_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, ExploreMetadataOutput)
    assert result.queryable_fields is None
    assert result.distinct_values is None
    assert error_message in result.error
    assert "Error getting queryable fields" in result.error
    mock_repo.get_queryable_fields.assert_called_once()
    mock_repo.get_distinct_values.assert_not_called()


@pytest.mark.asyncio
async def test_explore_metadata_get_distinct_values_error(run_context, mock_repo):
    """Test explore_metadata handles errors when getting distinct values."""
    # Arrange
    field_name = "issuing_agency"
    error_message = "Field not found"
    mock_repo.get_distinct_values.side_effect = Exception(error_message)
    input_params = ExploreMetadataInput(field=field_name)

    # Act
    result = await explore_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, ExploreMetadataOutput)
    assert result.queryable_fields is None
    assert result.distinct_values is None
    assert error_message in result.error
    assert f"Error getting distinct values for field '{field_name}'" in result.error
    mock_repo.get_distinct_values.assert_called_once_with(field_name)
    mock_repo.get_queryable_fields.assert_not_called()


# --- Tests for query_metadata ---


@pytest.mark.asyncio
async def test_query_metadata_success_found(run_context, mock_repo):
    """Test query_metadata successfully finds records and returns their IDs."""
    # Arrange
    filters = {"document_type": "Consent Order", "issuing_agency": "CFPB"}
    limit = 10
    # Create mock FileRecord objects with just an id attribute for simplicity
    mock_record_1 = MagicMock()
    mock_record_1.id = uuid.uuid4()
    mock_record_2 = MagicMock()
    mock_record_2.id = uuid.uuid4()
    expected_records = [mock_record_1, mock_record_2]
    expected_ids = [rec.id for rec in expected_records]
    mock_repo.find_by_metadata.return_value = expected_records
    input_params = QueryMetadataInput(filters=filters, limit=limit)

    # Act
    result = await query_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, QueryMetadataOutput)
    assert result.matching_doc_ids == expected_ids
    assert result.count == len(expected_ids)
    assert result.error is None
    mock_repo.find_by_metadata.assert_called_once_with(filters=filters, limit=limit)


@pytest.mark.asyncio
async def test_query_metadata_success_not_found(run_context, mock_repo):
    """Test query_metadata handles cases where no matching records are found."""
    # Arrange
    filters = {"document_type": "NonExistent"}
    mock_repo.find_by_metadata.return_value = []  # Return empty list
    input_params = QueryMetadataInput(filters=filters)

    # Act
    result = await query_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, QueryMetadataOutput)
    assert result.matching_doc_ids == []
    assert result.count == 0
    assert result.error is None
    mock_repo.find_by_metadata.assert_called_once_with(filters=filters, limit=None)


@pytest.mark.asyncio
async def test_query_metadata_error(run_context, mock_repo):
    """Test query_metadata handles exceptions during database query."""
    # Arrange
    filters = {"issuing_agency": "SEC"}
    error_message = "Query execution failed"
    mock_repo.find_by_metadata.side_effect = Exception(error_message)
    input_params = QueryMetadataInput(filters=filters)

    # Act
    result = await query_metadata(run_context, input_params)

    # Assert
    assert isinstance(result, QueryMetadataOutput)
    assert result.matching_doc_ids == []
    assert result.count == 0
    assert error_message in result.error
    assert f"Error querying metadata with filters {filters}" in result.error
    mock_repo.find_by_metadata.assert_called_once_with(filters=filters, limit=None)
