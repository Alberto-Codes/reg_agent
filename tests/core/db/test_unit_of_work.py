# tests/core/db/test_unit_of_work.py
from unittest.mock import MagicMock, patch

import pytest

from reg_agent.core.db.repositories import DocumentRepository

# Import the class to test
from reg_agent.core.db.unit_of_work import SqlModelUnitOfWork


@pytest.fixture
def mock_session_context():
    """Mocks the context manager returned by get_session."""
    mock_cm = MagicMock()
    # Mock the session object returned when entering the context
    mock_session = MagicMock(name="MockSession")
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = None  # Simulate successful exit by default
    return mock_cm, mock_session


@patch("reg_agent.core.db.unit_of_work.get_session")
def test_uow_enter_exit_success(mock_get_session, mock_session_context):
    """Test successful entry, commit, and exit."""
    mock_cm, mock_session = mock_session_context
    mock_get_session.return_value = mock_cm

    with SqlModelUnitOfWork() as uow:
        # Check repository is initialized
        assert isinstance(uow.documents, DocumentRepository)
        assert uow.documents.session == mock_session
        # Simulate doing some work
        pass

    # Assertions on exit
    mock_get_session.assert_called_once()
    mock_cm.__enter__.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    mock_cm.__exit__.assert_called_once()  # UoW.close calls this


@patch("reg_agent.core.db.unit_of_work.get_session")
def test_uow_exit_with_exception(mock_get_session, mock_session_context):
    """Test rollback and exit when an exception occurs."""
    mock_cm, mock_session = mock_session_context
    mock_get_session.return_value = mock_cm

    with pytest.raises(ValueError, match="Test Exception"):
        with SqlModelUnitOfWork() as uow:
            # Check repository is initialized
            assert isinstance(uow.documents, DocumentRepository)
            # Simulate an error during work
            raise ValueError("Test Exception")

    # Assertions on exit
    mock_get_session.assert_called_once()
    mock_cm.__enter__.assert_called_once()
    mock_session.commit.assert_not_called()  # Commit should not be called
    mock_session.rollback.assert_called_once()  # Rollback should be called
    mock_cm.__exit__.assert_called_once()  # UoW.close calls this


@patch("reg_agent.core.db.unit_of_work.get_session")
def test_uow_commit_failure_rolls_back(mock_get_session, mock_session_context):
    """Test that rollback occurs if commit fails."""
    mock_cm, mock_session = mock_session_context
    mock_get_session.return_value = mock_cm
    # Simulate commit failing
    commit_error = Exception("Commit Failed")
    mock_session.commit.side_effect = commit_error

    with pytest.raises(Exception, match="Commit Failed"):
        with SqlModelUnitOfWork() as _:
            pass  # Exit normally to trigger commit

    # Assertions on exit
    mock_get_session.assert_called_once()
    mock_cm.__enter__.assert_called_once()
    mock_session.commit.assert_called_once()  # Commit was attempted
    mock_session.rollback.assert_called_once()  # Rollback should be called
    mock_cm.__exit__.assert_called_once()


@patch("reg_agent.core.db.unit_of_work.get_session")
def test_uow_rollback_failure_logged(mock_get_session, mock_session_context, caplog):
    """Test that rollback failure is logged but doesn't prevent closing."""
    mock_cm, mock_session = mock_session_context
    mock_get_session.return_value = mock_cm
    # Simulate rollback failing (e.g., during exception handling)
    rollback_error = Exception("Rollback Failed")
    mock_session.rollback.side_effect = rollback_error

    with pytest.raises(ValueError, match="Test Exception"):
        with SqlModelUnitOfWork() as _:
            raise ValueError("Test Exception")  # Trigger rollback path

    # Assertions on exit
    mock_get_session.assert_called_once()
    mock_cm.__enter__.assert_called_once()
    mock_session.commit.assert_not_called()
    mock_session.rollback.assert_called_once()  # Rollback was attempted
    mock_cm.__exit__.assert_called_once()

    # Check logs for rollback error
    assert "Exception during UoW rollback." in caplog.text
    assert "Rollback Failed" in caplog.text
