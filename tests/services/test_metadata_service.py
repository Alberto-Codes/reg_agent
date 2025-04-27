# tests/services/test_metadata_service.py

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
import google.auth.exceptions
from pydantic import BaseModel

# Modules to test
from reg_agent.services.metadata_service import MetadataExtractionService
from reg_agent.schemas.metadata import RegulationDocumentMetadata
from reg_agent.auth.token_manager import ImpersonatedTokenManager
from reg_agent.auth.http_auth import DynamicBearerAuth
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai import Agent

# Mock configuration variables used by the service
MOCK_MODEL_NAME = "mock-gemini-model"
MOCK_BASE_URL = "https://mock.googleapis.com/v1/mock-endpoint"
MOCK_TARGET_SA = "mock-sa@mock-project.iam.gserviceaccount.com"

# --- Fixtures ---

@pytest.fixture(autouse=True)
def mock_config(mocker):
    """Mocks configuration variables used during service initialization."""
    mocker.patch("reg_agent.services.metadata_service.MODEL_NAME", MOCK_MODEL_NAME)
    mocker.patch("reg_agent.services.metadata_service.BASE_URL", MOCK_BASE_URL)
    mocker.patch("reg_agent.services.metadata_service.REQUEST_TIMEOUT_SECONDS", 180.0)
    mocker.patch("reg_agent.services.metadata_service.CONNECT_TIMEOUT_SECONDS", 20.0)
    mocker.patch("reg_agent.services.metadata_service.MAX_RETRIES", 3) # Mock retries

@pytest.fixture
def mock_agent_constructor(mocker):
    """Mocks the pydantic_ai.Agent constructor and the instance."""
    mock_agent_instance = mocker.MagicMock(spec=Agent)
    dummy_metadata = RegulationDocumentMetadata(document_type="Mocked", issuing_agency="Mock", subject_institution="Mock", document_identifier="Mock-001", summary="Mocked summary.")
    # Mock the agent's run method result
    mock_agent_instance.run = AsyncMock(return_value=MagicMock(output=dummy_metadata))
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.Agent", return_value=mock_agent_instance)
    return mock_constructor, mock_agent_instance

@pytest.fixture
def mock_openai_model_constructor(mocker):
    """Mocks the pydantic_ai.models.openai.OpenAIModel constructor."""
    mock_model_instance = mocker.MagicMock(spec=OpenAIModel)
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.OpenAIModel", return_value=mock_model_instance)
    return mock_constructor, mock_model_instance

@pytest.fixture
def mock_openai_provider_constructor(mocker):
    """Mocks the pydantic_ai.providers.openai.OpenAIProvider constructor."""
    mock_provider_instance = mocker.MagicMock(spec=OpenAIProvider)
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.OpenAIProvider", return_value=mock_provider_instance)
    return mock_constructor, mock_provider_instance

@pytest.fixture
def mock_google_auth(mocker):
    """Mocks google.auth routines for Direct ADC."""
    mock_creds = MagicMock()
    mock_creds.token = "mock-adc-token"
    mock_default = mocker.patch("reg_agent.services.metadata_service.google.auth.default", return_value=(mock_creds, "mock-project"))
    mock_request = mocker.patch("reg_agent.services.metadata_service.google.auth.transport.requests.Request")
    mock_creds.refresh = MagicMock()
    return mock_default, mock_request, mock_creds

@pytest.fixture
def mock_token_manager(mocker):
    """Mocks the ImpersonatedTokenManager."""
    mock_tm_instance = mocker.MagicMock(spec=ImpersonatedTokenManager)
    mock_tm_instance.target_service_account = MOCK_TARGET_SA # Simulate resolved SA
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.ImpersonatedTokenManager", return_value=mock_tm_instance)
    return mock_constructor, mock_tm_instance

@pytest.fixture
def mock_dynamic_auth(mocker):
    """Mocks the DynamicBearerAuth."""
    mock_auth_instance = mocker.MagicMock(spec=DynamicBearerAuth)
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.DynamicBearerAuth", return_value=mock_auth_instance)
    return mock_constructor, mock_auth_instance

@pytest.fixture
def mock_httpx_client(mocker):
    """Mocks the httpx.AsyncClient constructor and instance."""
    mock_client_instance = AsyncMock(spec=httpx.AsyncClient)
    mock_client_instance.aclose = AsyncMock()
    # Add timeout attribute as the service reads it for logging
    mock_client_instance.timeout = httpx.Timeout(180.0, connect=20.0)
    mock_constructor = mocker.patch("reg_agent.services.metadata_service.httpx.AsyncClient", return_value=mock_client_instance)
    return mock_constructor, mock_client_instance

# --- Test Cases ---

# Initialization Tests
def test_init_direct_adc_success(mocker, mock_config, mock_google_auth, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test successful initialization using Direct ADC."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)
    mock_provider_constructor, _ = mock_openai_provider_constructor
    mock_model_constructor, mock_model_instance = mock_openai_model_constructor
    mock_agent_constr, mock_agent_instance = mock_agent_constructor

    service = MetadataExtractionService()

    assert service.agent == mock_agent_instance
    mock_google_auth[0].assert_called_once() # google.auth.default
    mock_google_auth[2].refresh.assert_called_once() # credentials.refresh
    # Check provider called correctly
    mock_provider_constructor.assert_called_once_with(
        base_url=MOCK_BASE_URL,
        api_key="mock-adc-token"
    )
    # Check model called correctly
    mock_model_constructor.assert_called_once_with(
        MOCK_MODEL_NAME,
        provider=mock_provider_constructor.return_value,
    )
    # Check agent called correctly
    mock_agent_constr.assert_called_once_with(
        model=mock_model_instance,
        output_type=RegulationDocumentMetadata
    )

def test_init_impersonation_success(mocker, mock_config, mock_token_manager, mock_dynamic_auth, mock_httpx_client, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test successful initialization using Impersonation."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", MOCK_TARGET_SA)
    mock_tm_constructor, mock_tm_instance = mock_token_manager
    mock_auth_constructor, mock_auth_instance = mock_dynamic_auth
    mock_client_constructor, mock_client_instance = mock_httpx_client
    mock_provider_constructor, mock_provider_instance = mock_openai_provider_constructor
    mock_model_constructor, mock_model_instance = mock_openai_model_constructor
    mock_agent_constr, mock_agent_instance = mock_agent_constructor

    service = MetadataExtractionService()

    assert service.agent == mock_agent_instance
    assert service.http_client == mock_client_instance
    assert service.token_manager == mock_tm_instance

    mock_tm_constructor.assert_called_once_with(target_service_account_name_or_email=MOCK_TARGET_SA)
    mock_auth_constructor.assert_called_once_with(mock_tm_instance)
    mock_client_constructor.assert_called_once()
    # Check httpx client args
    call_args, call_kwargs = mock_client_constructor.call_args
    assert call_kwargs.get('auth') == mock_auth_instance
    assert isinstance(call_kwargs.get('timeout'), httpx.Timeout)
    # Check provider called correctly
    mock_provider_constructor.assert_called_once_with(
        base_url=MOCK_BASE_URL,
        http_client=mock_client_instance
    )
    # Check model called correctly
    mock_model_constructor.assert_called_once_with(
        MOCK_MODEL_NAME,
        provider=mock_provider_instance,
    )
    # Check agent called correctly
    mock_agent_constr.assert_called_once_with(
        model=mock_model_instance,
        output_type=RegulationDocumentMetadata
    )

def test_init_direct_adc_fails_no_creds(mocker, mock_config):
    """Test initialization failure when google.auth.default fails."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)
    mocker.patch("reg_agent.services.metadata_service.google.auth.default", side_effect=google.auth.exceptions.DefaultCredentialsError("No creds"))
    mock_openai_provider = mocker.patch("reg_agent.services.metadata_service.OpenAIProvider") # Prevent downstream errors

    with pytest.raises(RuntimeError, match="missing ADC"):
        MetadataExtractionService()
    mock_openai_provider.assert_not_called()

def test_init_impersonation_fails_tm_init(mocker, mock_config):
    """Test initialization failure when ImpersonatedTokenManager fails."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", MOCK_TARGET_SA)
    mocker.patch("reg_agent.services.metadata_service.ImpersonatedTokenManager", side_effect=Exception("TM init failed"))
    mock_openai_provider = mocker.patch("reg_agent.services.metadata_service.OpenAIProvider") # Prevent downstream errors

    with pytest.raises(RuntimeError, match="token manager setup"):
        MetadataExtractionService()
    mock_openai_provider.assert_not_called()

# --- extract_metadata Tests ---

@pytest.mark.asyncio
async def test_extract_metadata_success(mocker, mock_config, mock_google_auth, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test successful metadata extraction call."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)
    _, mock_agent_instance = mock_agent_constructor

    service = MetadataExtractionService()

    input_text = "This is the document text."
    result = await service.extract_metadata(input_text)

    assert isinstance(result, RegulationDocumentMetadata)
    assert result.document_type == "Mocked"
    mock_agent_instance.run.assert_called_once()
    call_args, call_kwargs = mock_agent_instance.run.call_args
    assert input_text in call_args[0]

@pytest.mark.asyncio
async def test_extract_metadata_empty_text(mocker, mock_config, mock_google_auth, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test extract_metadata with empty input text."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)
    _, mock_agent_instance = mock_agent_constructor

    service = MetadataExtractionService()
    result = await service.extract_metadata("")

    assert result is None
    mock_agent_instance.run.assert_not_called()

@pytest.mark.asyncio
async def test_extract_metadata_agent_exception(mocker, mock_config, mock_google_auth, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test extract_metadata when the agent raises an exception."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)
    _, mock_agent_instance = mock_agent_constructor
    mock_agent_instance.run.side_effect = Exception("Agent failed")

    service = MetadataExtractionService()
    result = await service.extract_metadata("Some text")

    assert result is None
    mock_agent_instance.run.assert_called_once()

# --- close Tests ---

@pytest.mark.asyncio
async def test_close_with_impersonation(mocker, mock_config, mock_token_manager, mock_dynamic_auth, mock_httpx_client, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test that close calls http_client.aclose when using impersonation."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", MOCK_TARGET_SA)
    _, mock_client_instance = mock_httpx_client

    service = MetadataExtractionService()
    assert service.http_client is mock_client_instance # Verify client was set during init

    await service.close()

    mock_client_instance.aclose.assert_called_once()
    assert service.http_client is None # Check client is set to None after close

@pytest.mark.asyncio
async def test_close_with_direct_adc(mocker, mock_config, mock_google_auth, mock_openai_provider_constructor, mock_openai_model_constructor, mock_agent_constructor):
    """Test that close does nothing when using direct ADC (no custom client)."""
    mocker.patch("reg_agent.services.metadata_service.TARGET_SA_NAME_OR_EMAIL", None)

    service = MetadataExtractionService()
    assert service.http_client is None # Verify no client was set

    # Should not raise error and http_client should remain None
    await service.close()
    assert service.http_client is None 