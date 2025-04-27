import pytest
import httpx
from unittest.mock import MagicMock

from src.reg_agent.auth.http_auth import DynamicBearerAuth
from src.reg_agent.auth.token_manager import ImpersonatedTokenManager


def test_dynamic_bearer_auth_flow():
    """Tests that the auth_flow method retrieves a token and sets the header."""
    # Arrange
    mock_token = "mock-bearer-token"
    mock_token_manager = MagicMock(spec=ImpersonatedTokenManager)
    mock_token_manager.get_token.return_value = mock_token

    auth = DynamicBearerAuth(token_manager=mock_token_manager)
    dummy_request = httpx.Request("GET", "https://example.com")

    # Act
    # Iterate through the generator to execute the flow
    flow_generator = auth.auth_flow(dummy_request)
    updated_request = next(flow_generator)

    # Assert
    mock_token_manager.get_token.assert_called_once()
    assert "authorization" in updated_request.headers
    assert updated_request.headers["authorization"] == f"Bearer {mock_token}"

    # Ensure the generator is exhausted (optional good practice)
    with pytest.raises(StopIteration):
        next(flow_generator) 