# tests/auth/test_token_manager.py

import datetime
from unittest.mock import ANY, MagicMock

import google.auth
import google.auth.exceptions
import google.auth.impersonated_credentials
import pytest

from reg_agent.auth.token_manager import REFRESH_BUFFER, ImpersonatedTokenManager

MOCK_TARGET_SA_EMAIL = "test-target-sa@test-project.iam.gserviceaccount.com"
MOCK_TARGET_SA_NAME = "test-target-sa"
MOCK_PROJECT_ID = "test-project"
MOCK_SOURCE_TOKEN = "source-token"
MOCK_IMPERSONATED_TOKEN = "impersonated-token"
MOCK_SCOPES = ["https://www.googleapis.com/auth/test.scope"]

# --- Fixtures ---


@pytest.fixture
def mock_google_auth_default(mocker):
    """Mocks google.auth.default to return controlled creds and project ID."""
    mock_creds = MagicMock(spec=google.auth.credentials.Credentials)
    mock_creds.token = MOCK_SOURCE_TOKEN
    mock_creds.service_account_email = "caller-sa@test-project.iam.gserviceaccount.com"
    mock_default = mocker.patch(
        "reg_agent.auth.token_manager.google.auth.default",
        return_value=(mock_creds, MOCK_PROJECT_ID),
    )
    return mock_default, mock_creds


@pytest.fixture
def mock_google_auth_default_no_project(mocker):
    """Mocks google.auth.default returning creds but no project ID."""
    mock_creds = MagicMock(spec=google.auth.credentials.Credentials)
    mock_creds.token = MOCK_SOURCE_TOKEN
    mock_creds.service_account_email = "caller-sa@test-project.iam.gserviceaccount.com"
    mock_default = mocker.patch(
        "reg_agent.auth.token_manager.google.auth.default",
        return_value=(mock_creds, None),  # No project ID
    )
    return mock_default, mock_creds


@pytest.fixture
def mock_impersonated_creds_constructor(mocker):
    """Mocks the Impersonated Credentials constructor and refresh method."""
    mock_instance = MagicMock(spec=google.auth.impersonated_credentials.Credentials)
    mock_instance.token = MOCK_IMPERSONATED_TOKEN
    # Use a fixed, known future expiry for consistency in mocks
    mock_instance.expiry = datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0
    ) + datetime.timedelta(hours=1)
    mock_instance.refresh = MagicMock()
    mock_constructor = mocker.patch(
        "reg_agent.auth.token_manager.google.auth.impersonated_credentials.Credentials",
        return_value=mock_instance,
    )
    return mock_constructor, mock_instance


@pytest.fixture
def mock_datetime_now(mocker):
    """Mocks datetime.datetime.now to return a fixed, controllable time."""
    # Use a fixed, known time for consistent testing
    frozen_time = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    # Patch just the 'now' method of the datetime class within the target module
    mock_now = mocker.patch("reg_agent.auth.token_manager.datetime.datetime")
    mock_now.now.return_value = frozen_time
    # Allow other datetime methods to work (like timedelta)
    mock_now.side_effect = lambda *args, **kw: datetime.datetime(*args, **kw)
    mock_now.timezone = datetime.timezone  # Ensure timezone info is available
    return mock_now, frozen_time


# --- Test Cases: Initialization ---


def test_init_success_with_email(mock_google_auth_default):
    """Test successful initialization with full target SA email."""
    mock_default, _ = mock_google_auth_default
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL,
        scopes=MOCK_SCOPES,
        lifetime_seconds=1800,
    )
    mock_default.assert_called_once_with(scopes=MOCK_SCOPES)
    assert manager.target_service_account == MOCK_TARGET_SA_EMAIL
    assert manager.scopes == MOCK_SCOPES
    assert manager.lifetime_seconds == 1800
    assert manager._project_id == MOCK_PROJECT_ID
    assert manager._cached_token is None
    assert manager._token_expiry is None


def test_init_success_with_name(mock_google_auth_default):
    """Test successful initialization with target SA name (constructs email)."""
    mock_default, _ = mock_google_auth_default
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_NAME,
        scopes=MOCK_SCOPES,  # Use custom scope
    )
    expected_email = f"{MOCK_TARGET_SA_NAME}@{MOCK_PROJECT_ID}.iam.gserviceaccount.com"
    mock_default.assert_called_once_with(scopes=MOCK_SCOPES)
    assert manager.target_service_account == expected_email
    assert manager.scopes == MOCK_SCOPES
    assert manager.lifetime_seconds == 3300  # Default lifetime
    assert manager._project_id == MOCK_PROJECT_ID


def test_init_failure_empty_target(mock_google_auth_default):
    """Test initialization failure with empty target SA."""
    with pytest.raises(ValueError, match="cannot be empty"):
        ImpersonatedTokenManager(target_service_account_name_or_email="")


def test_init_failure_google_auth_default_fails(mocker):
    """Test initialization failure when google.auth.default raises error."""
    mocker.patch(
        "reg_agent.auth.token_manager.google.auth.default",
        side_effect=google.auth.exceptions.DefaultCredentialsError("ADC not found"),
    )
    with pytest.raises(google.auth.exceptions.DefaultCredentialsError):
        ImpersonatedTokenManager(
            target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
        )


def test_init_failure_construct_email_no_project_id(
    mock_google_auth_default_no_project,
):
    """Test init failure when SA name is given but project ID is unknown."""
    mock_default, _ = mock_google_auth_default_no_project
    with pytest.raises(ValueError, match="Project ID unknown"):
        ImpersonatedTokenManager(
            target_service_account_name_or_email=MOCK_TARGET_SA_NAME
        )
    mock_default.assert_called_once()  # Ensure default was called


# --- Test Cases: _is_token_valid ---


def test_is_token_valid_no_token(mock_google_auth_default, mock_datetime_now):
    """Test _is_token_valid when no token is cached."""
    _, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    manager._cached_token = None
    manager._token_expiry = frozen_time + datetime.timedelta(hours=1)
    assert not manager._is_token_valid()


def test_is_token_valid_no_expiry(mock_google_auth_default, mock_datetime_now):
    """Test _is_token_valid when expiry is not set."""
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    manager._cached_token = MOCK_IMPERSONATED_TOKEN
    manager._token_expiry = None
    assert not manager._is_token_valid()


def test_is_token_valid_within_buffer(mock_google_auth_default, mock_datetime_now):
    """Test _is_token_valid when token expires within the refresh buffer."""
    mock_dt, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    manager._cached_token = MOCK_IMPERSONATED_TOKEN
    # Set expiry to be just inside the buffer period from the frozen time
    manager._token_expiry = (
        frozen_time + REFRESH_BUFFER - datetime.timedelta(seconds=10)
    )
    # mock_dt.now.return_value = frozen_time # Already set by fixture
    assert not manager._is_token_valid()


def test_is_token_valid_expired(mock_google_auth_default, mock_datetime_now):
    """Test _is_token_valid when token is expired."""
    mock_dt, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    manager._cached_token = MOCK_IMPERSONATED_TOKEN
    manager._token_expiry = frozen_time - datetime.timedelta(
        seconds=10
    )  # Expired 10s before frozen time
    # mock_dt.now.return_value = frozen_time # Already set by fixture
    assert not manager._is_token_valid()


def test_is_token_valid_success(mock_google_auth_default, mock_datetime_now):
    """Test _is_token_valid when token is valid and outside buffer."""
    mock_dt, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    manager._cached_token = MOCK_IMPERSONATED_TOKEN
    # Set expiry well outside the buffer period from the frozen time
    manager._token_expiry = (
        frozen_time + REFRESH_BUFFER + datetime.timedelta(minutes=10)
    )
    # mock_dt.now.return_value = frozen_time # Already set by fixture
    assert manager._is_token_valid()


# --- Test Cases: _generate_new_token ---


def test_generate_new_token_success(
    mock_google_auth_default, mock_impersonated_creds_constructor
):
    """Test successful generation of a new token."""
    mock_default, mock_source_creds = mock_google_auth_default
    mock_creds_constructor, mock_creds_instance = mock_impersonated_creds_constructor

    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL,
        scopes=MOCK_SCOPES,
        lifetime_seconds=1200,
    )

    token, expiry = manager._generate_new_token()

    mock_creds_constructor.assert_called_once_with(
        source_credentials=mock_source_creds,
        target_principal=MOCK_TARGET_SA_EMAIL,
        target_scopes=MOCK_SCOPES,
        lifetime=1200,
    )
    mock_creds_instance.refresh.assert_called_once_with(
        ANY
    )  # ANY checks for a Request object
    assert token == MOCK_IMPERSONATED_TOKEN
    assert expiry == mock_creds_instance.expiry


def test_generate_new_token_constructor_fails(
    mock_google_auth_default, mock_impersonated_creds_constructor
):
    """Test failure when Credentials constructor raises an exception."""
    mock_creds_constructor, _ = mock_impersonated_creds_constructor
    mock_creds_constructor.side_effect = ValueError("Invalid scope")

    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    with pytest.raises(RuntimeError, match="Failed to generate token"):
        manager._generate_new_token()


def test_generate_new_token_refresh_fails(
    mock_google_auth_default, mock_impersonated_creds_constructor
):
    """Test failure when credentials refresh raises an exception."""
    mock_creds_constructor, mock_creds_instance = mock_impersonated_creds_constructor
    mock_creds_instance.refresh.side_effect = google.auth.exceptions.RefreshError(
        "Refresh failed"
    )

    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    with pytest.raises(RuntimeError, match="Failed to generate token"):
        manager._generate_new_token()
    mock_creds_instance.refresh.assert_called_once()


def test_generate_new_token_refresh_no_token(
    mock_google_auth_default, mock_impersonated_creds_constructor
):
    """Test failure when credentials refresh doesn't return a token."""
    mock_creds_constructor, mock_creds_instance = mock_impersonated_creds_constructor
    mock_creds_instance.token = None  # Simulate refresh not setting token
    # Need expiry set for the initial check in _generate_new_token
    mock_creds_instance.expiry = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(hours=1)

    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    # Expect the wrapped error message
    expected_error_msg = f"Failed to generate token for {MOCK_TARGET_SA_EMAIL}"
    with pytest.raises(RuntimeError, match=expected_error_msg):
        manager._generate_new_token()
    mock_creds_instance.refresh.assert_called_once()


# --- Test Cases: get_token ---


def test_get_token_cached_valid(mock_google_auth_default, mock_datetime_now):
    """Test get_token returns valid cached token without regenerating."""
    mock_dt, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )
    # Manually set a valid cached token
    manager._cached_token = "valid-cached-token"
    manager._token_expiry = (
        frozen_time + REFRESH_BUFFER + datetime.timedelta(minutes=30)
    )
    # mock_dt.now.return_value = frozen_time # Already set by fixture

    # Mock _generate_new_token to ensure it's not called
    manager._generate_new_token = MagicMock()

    token = manager.get_token()

    assert token == "valid-cached-token"
    manager._generate_new_token.assert_not_called()


def test_get_token_no_cache(
    mock_google_auth_default, mock_impersonated_creds_constructor, mock_datetime_now
):
    """Test get_token generates a new token when cache is empty."""
    mock_creds_const, mock_creds_inst = mock_impersonated_creds_constructor
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    assert manager._cached_token is None
    token = manager.get_token()

    assert token == MOCK_IMPERSONATED_TOKEN
    assert manager._cached_token == MOCK_IMPERSONATED_TOKEN
    assert manager._token_expiry == mock_creds_inst.expiry
    mock_creds_const.assert_called_once()
    mock_creds_inst.refresh.assert_called_once()


def test_get_token_cache_expired(
    mock_google_auth_default, mock_impersonated_creds_constructor, mock_datetime_now
):
    """Test get_token generates a new token when cache is expired."""
    mock_creds_const, mock_creds_inst = mock_impersonated_creds_constructor
    mock_dt, frozen_time = mock_datetime_now
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    # Set expired token
    manager._cached_token = "expired-token"
    manager._token_expiry = frozen_time - datetime.timedelta(minutes=10)
    # mock_dt.now.return_value = frozen_time # Already set by fixture

    token = manager.get_token()

    assert token == MOCK_IMPERSONATED_TOKEN
    assert manager._cached_token == MOCK_IMPERSONATED_TOKEN
    assert manager._token_expiry == mock_creds_inst.expiry
    mock_creds_const.assert_called_once()
    mock_creds_inst.refresh.assert_called_once()


def test_get_token_generation_fails(
    mock_google_auth_default, mock_impersonated_creds_constructor, mock_datetime_now
):
    """Test get_token raises RuntimeError when token generation fails."""
    mock_creds_const, mock_creds_inst = mock_impersonated_creds_constructor
    mock_creds_inst.refresh.side_effect = RuntimeError(
        "Original token gen failed"
    )  # Original error
    manager = ImpersonatedTokenManager(
        target_service_account_name_or_email=MOCK_TARGET_SA_EMAIL
    )

    # Expect the wrapped error message
    expected_error_msg = f"Failed to generate token for {MOCK_TARGET_SA_EMAIL}"
    with pytest.raises(RuntimeError, match=expected_error_msg):
        manager.get_token()

    assert manager._cached_token is None
    assert manager._token_expiry is None
