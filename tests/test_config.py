# tests/test_config.py
import os
import pytest

# We need to manipulate environment variables *before* importing the config module functions

@pytest.fixture(autouse=True)
def clear_config_imports(monkeypatch):
    '''Fixture to ensure config module is freshly imported for each test.'''
    # Remove the config module from sys.modules to force re-import
    # This is crucial because config logic runs at import time
    import sys
    if 'reg_agent.config' in sys.modules:
        monkeypatch.delitem(sys.modules, 'reg_agent.config')
    # Also ensure relevant variables are clean if needed, using monkeypatch.delenv
    # Example: monkeypatch.delenv('VERTEX_MODEL_NAME', raising=False)

def test_get_required_env_var_success(monkeypatch):
    '''Test retrieving a required env var that exists.'''
    var_name = 'TEST_REQUIRED_VAR'
    expected_value = 'test_value'
    monkeypatch.setenv(var_name, expected_value)

    # Import function *after* setting env var
    from reg_agent.config import _get_required_env_var

    assert _get_required_env_var(var_name) == expected_value

def test_get_required_env_var_missing(monkeypatch):
    '''Test retrieving a required env var that is missing.'''
    var_name = 'MISSING_REQUIRED_VAR'
    monkeypatch.delenv(var_name, raising=False) # Ensure it doesn't exist

    # Import function *after* clearing env var
    from reg_agent.config import _get_required_env_var

    with pytest.raises(ValueError, match=f'{var_name} must be set'):
        _get_required_env_var(var_name)

def test_get_vertex_model_name_default(monkeypatch):
    '''Test getting the default model name when env var is not set.'''
    monkeypatch.delenv('VERTEX_MODEL_NAME', raising=False)

    # Import function *after* clearing env var
    from reg_agent.config import _get_vertex_model_name

    # Default when unset seems to be based on some other logic/env
    assert _get_vertex_model_name() == 'google/gemini-2.5-flash-preview-04-17'

def test_get_vertex_model_name_set_with_prefix(monkeypatch):
    '''Test getting model name when set correctly with prefix.'''
    expected_model = 'google/my-custom-model-v1'
    monkeypatch.setenv('VERTEX_MODEL_NAME', expected_model)

    # Import function *after* setting env var
    from reg_agent.config import _get_vertex_model_name

    assert _get_vertex_model_name() == expected_model

def test_get_vertex_model_name_missing_prefix(monkeypatch):
    '''Test adding the 'google/' prefix if missing.'''
    model_without_prefix = 'gemini-pro'
    expected_model = 'google/gemini-pro'
    monkeypatch.setenv('VERTEX_MODEL_NAME', model_without_prefix)

    # Import function *after* setting env var
    from reg_agent.config import _get_vertex_model_name

    assert _get_vertex_model_name() == expected_model

def test_get_vertex_model_name_empty_var(monkeypatch):
    '''Test using default when env var is set to an empty string.'''
    monkeypatch.setenv('VERTEX_MODEL_NAME', '')

    # Import function *after* setting env var
    from reg_agent.config import _get_vertex_model_name

    # Default when explicitly empty uses the hardcoded default
    assert _get_vertex_model_name() == 'google/gemini-1.5-flash-latest' 