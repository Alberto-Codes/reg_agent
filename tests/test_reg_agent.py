"""Tests for reg_agent package."""

# import pytest # NOTE: pytest is not directly used in the modified test, can be removed if desired.
from unittest.mock import patch

from reg_agent import main


@patch("reg_agent.ConsentOrderDownloader")
def test_main_initializes_and_runs_downloader(mock_downloader_class):
    """Test that main initializes ConsentOrderDownloader and calls run()."""
    # Arrange
    mock_downloader_instance = mock_downloader_class.return_value

    # Act
    main()

    # Assert
    mock_downloader_class.assert_called_once_with()  # Check if __init__ was called
    mock_downloader_instance.run.assert_called_once_with()  # Check if run() was called
