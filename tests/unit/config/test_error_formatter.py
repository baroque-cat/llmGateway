"""Tests for src/config/error_formatter.py — get_line_number and handle_validation_error."""

import sys
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

from src.config.error_formatter import get_line_number, handle_validation_error

# ---------------------------------------------------------------------------
# Helpers: create a fake ruamel.yaml CommentedMap with .lc attribute
# ---------------------------------------------------------------------------


class _FakeCommentedMap(dict):
    """A dict subclass that mimics ruamel.yaml CommentedMap with .lc attribute."""

    def __init__(self, *args, lc_data: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lc = _FakeLineCol(lc_data or {})


class _FakeLineCol:
    """Mimics ruamel.yaml .lc attribute with .data dict."""

    def __init__(self, data: dict):
        self.data = data


# ---------------------------------------------------------------------------
# Tests for get_line_number
# ---------------------------------------------------------------------------


def test_get_line_number_with_ruamel_yaml():
    """When raw_yaml_dict is a ruamel.yaml CommentedMap with .lc.line data,
    get_line_number should return the correct 1-indexed line number."""
    commented_map = _FakeCommentedMap(
        {
            "providers": _FakeCommentedMap(
                {"anthropic": _FakeCommentedMap({"enabled": True})}
            )
        },
        lc_data={"providers": [4, 0, 0]},  # 0-indexed line=4 → 1-indexed=5
    )

    result = get_line_number(commented_map, ("providers",))
    assert result == 5


def test_get_line_number_with_plain_dict():
    """When raw_yaml_dict is a plain dict (no .lc attribute),
    get_line_number should return None."""
    plain_dict = {"providers": {"anthropic": {"enabled": True}}}

    result = get_line_number(plain_dict, ("providers",))
    assert result is None


def test_get_line_number_nested_key():
    """When error_path is nested (e.g. providers.anthropic.enabled),
    get_line_number should traverse into the nested structure and
    return the line number of the deepest key found with .lc data."""
    inner_map = _FakeCommentedMap(
        {"enabled": True},
        lc_data={"enabled": [12, 0, 0]},  # enabled at 0-indexed line 12 → 1-indexed=13
    )
    middle_map = _FakeCommentedMap(
        {"anthropic": inner_map},
        lc_data={"anthropic": [8, 0, 0]},
    )
    outer_map = _FakeCommentedMap(
        {"providers": middle_map},
        lc_data={"providers": [2, 0, 0]},
    )

    # Path: (providers, anthropic, enabled)
    # Traversal ends at parent=inner_map, last_key="enabled"
    result = get_line_number(outer_map, ("providers", "anthropic", "enabled"))
    assert result == 13  # 0-indexed 12 + 1 = 13


def test_get_line_number_key_not_found():
    """When the key in error_path does not exist in the dict,
    get_line_number should return None because traversal breaks early
    and the parent dict won't have .lc data for the missing key."""
    commented_map = _FakeCommentedMap(
        {"providers": _FakeCommentedMap({}, lc_data={})},
        lc_data={"providers": [2, 0, 0]},
    )

    result = get_line_number(commented_map, ("providers", "nonexistent_key"))
    assert result is None


# ---------------------------------------------------------------------------
# Tests for handle_validation_error
# ---------------------------------------------------------------------------


class _BadModel(BaseModel):
    """A tiny model that always fails validation for testing."""

    value: int  # noqa: RUF012 — Pydantic field annotation


def test_handle_validation_error_exits():
    """handle_validation_error should call sys.exit(1) and write error messages to stderr."""
    # Create a real ValidationError
    with pytest.raises(ValidationError) as exc_info:
        _BadModel(value="not_an_int")  # type: ignore[arg-type]

    validation_error = exc_info.value

    # Patch print to capture stderr output, and let sys.exit(1) raise SystemExit
    with patch("builtins.print") as mock_print:
        with pytest.raises(SystemExit) as exit_info:
            handle_validation_error(validation_error, {})

        # Verify sys.exit(1) was called
        assert exit_info.value.code == 1

        # Verify print was called with file=sys.stderr for error messages
        stderr_calls = [
            call
            for call in mock_print.call_args_list
            if call.kwargs.get("file") == sys.stderr
        ]
        assert len(stderr_calls) > 0

        # Verify the output contains "CONFIGURATION ERROR"
        stderr_output = "".join(
            str(call.args[0]) if call.args else "" for call in stderr_calls
        )
        assert "CONFIGURATION ERROR" in stderr_output
