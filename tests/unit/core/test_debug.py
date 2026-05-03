"""Tests for DebugMode constants in src.core.constants."""

import pytest

from src.core.constants import DebugMode


def test_debug_mode_constants():
    """Test that debug mode constants are defined correctly."""
    # Verify NO_CONTENT value
    assert DebugMode.NO_CONTENT.value == "no_content"

    # Verify HEADERS_ONLY does NOT exist (removed in refactor)
    with pytest.raises(AttributeError):
        DebugMode.HEADERS_ONLY