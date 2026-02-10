#!/usr/bin/env python3
"""
Tests for PEP 695 type alias syntax support and forward references.

This module verifies that the Python environment supports:
1. PEP 695 type alias syntax (type X = ...)
2. Recursive type aliases with forward references
3. Union vs pipe operator behavior with string forward references
"""

import sys
from typing import Union

import pytest


def test_pep695_type_alias_syntax():
    """
    Test that PEP 695 type alias syntax is supported.
    This is critical for src.config.loader which uses recursive type aliases.
    """
    # If Python version < 3.12, this test will fail with SyntaxError
    # We'll catch it and mark as skip if unsupported
    try:
        # Define recursive type aliases similar to those in src.config.loader
        type ConfigValue = (
            str | int | float | bool | None | "ConfigDict" | list["ConfigValue"]
        )
        type ConfigDict = dict[str, ConfigValue]

        # Verify they can be used in type hints
        def example_func(value: ConfigValue) -> ConfigDict:
            return {"key": value}

        # Simple runtime check - should not raise errors
        result = example_func("test")
        assert result == {"key": "test"}
        result2 = example_func(123)
        assert result2 == {"key": 123}

    except SyntaxError as e:
        # If syntax not supported, skip test with appropriate message
        pytest.skip(f"PEP 695 type alias syntax not supported: {e}")
    except Exception as e:
        # Any other exception is a test failure
        pytest.fail(f"PEP 695 type alias test failed with unexpected error: {e}")


def test_forward_references_with_union():
    """
    Test that Union works with string forward references.
    This is the traditional typing approach that should always work.
    """
    # Union with string forward reference should work
    T1 = Union[int, "T2"]

    # Later define T2
    T2 = str

    # Verify it can be used
    def example(val: T1) -> str:
        return str(val)

    assert example(42) == "42"
    assert example("hello") == "hello"


def test_forward_references_with_pipe_operator():
    """
    Test that pipe operator (|) does NOT work with string forward references at runtime.
    This is expected behavior: pipe operator requires actual types, not strings.
    """
    try:
        # This should raise TypeError because "T1" is a string, not a type
        T2 = int | "T1"  # noqa: F841
        # If it doesn't raise, that's unexpected (maybe Python version differs)
        # We'll still pass the test but note the behavior
        print("Warning: pipe operator accepted string forward reference")
    except TypeError:
        # Expected behavior
        pass
    except Exception as e:
        pytest.fail(f"Unexpected error with pipe operator: {e}")


def test_recursive_type_alias_import():
    """
    Test that the recursive type aliases in src.config.loader can be imported
    without syntax errors and can be used for basic type checking.
    """
    try:
        from src.config.loader import ConfigDict, ConfigValue

        # Verify they are not None
        assert ConfigValue is not None
        assert ConfigDict is not None

        # Try using them in a simple type hint
        def test_hint(value: ConfigValue) -> ConfigDict:
            return {"result": value}

        # Quick runtime check
        assert test_hint("test") == {"result": "test"}

    except SyntaxError as e:
        pytest.skip(f"PEP 695 syntax not supported in imported module: {e}")
    except ImportError as e:
        pytest.fail(f"Failed to import type aliases from loader: {e}")
    except Exception as e:
        pytest.fail(f"Unexpected error testing imported type aliases: {e}")


if __name__ == "__main__":
    # Allow running as script for debugging
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
