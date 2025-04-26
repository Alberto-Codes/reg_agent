"""Tests for reg_agent package."""

import pytest

from reg_agent import main


def test_main_returns_greeting():
    """Test that main returns the expected greeting message."""
    assert main() == "Hello from reg-agent!"
