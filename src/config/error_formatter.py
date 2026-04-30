#!/usr/bin/env python3

"""
Error Formatter Module - Formats Pydantic ValidationError into human-readable CLI output.

This module intercepts Pydantic validation errors, extracts line numbers from the original
ruamel.yaml structure using .lc.data metadata, and produces clean error reports without
Python tracebacks.
"""

import sys
from typing import Any, cast

from pydantic import ValidationError


def get_line_number(
    raw_yaml_dict: dict[str, Any], error_path: tuple[Any, ...]
) -> int | None:
    """
    Traverse the ruamel.yaml CommentedMap to find the line number for the specific field
    that triggered the validation error.

    Args:
        raw_yaml_dict: The original YAML structure loaded by ruamel.yaml (before merging).
        error_path: Tuple representing the path to the error field from Pydantic ValidationError.

    Returns:
        Line number (1-indexed) if found, None otherwise.
    """
    current = raw_yaml_dict
    parent = None
    last_key = None

    try:
        for key in error_path:
            if isinstance(current, dict):
                parent = current
                last_key = key
                if key in current:
                    current = current[key]
                else:
                    break

        # ruamel.yaml stores line info in .lc.data[key][0] (0-indexed)
        if (
            parent is not None
            and hasattr(parent, "lc")
            and cast(Any, parent).lc.data
            and last_key in cast(Any, parent).lc.data
        ):
            return cast(Any, parent).lc.data[last_key][0] + 1
    except Exception:
        pass

    return None


def handle_validation_error(e: ValidationError, raw_yaml_dict: dict[str, Any]) -> None:
    """
    Format Pydantic ValidationError into a beautiful CLI output without traceback.

    Args:
        e: The Pydantic ValidationError exception.
        raw_yaml_dict: The original YAML structure loaded by ruamel.yaml (before merging).
    """
    print("\n❌ CONFIGURATION ERROR:\n", file=sys.stderr)

    for error in e.errors():
        # Build path string: e.g., providers -> gemini -> debug_mode
        path_str = " -> ".join(str(p) for p in error["loc"])
        msg = error["msg"]

        line_num = get_line_number(raw_yaml_dict, error["loc"])
        line_info = f" (Line {line_num})" if line_num else ""

        print(f"• Field: [{path_str}]{line_info}", file=sys.stderr)
        print(f"  Issue: {msg}\n", file=sys.stderr)

    print(
        "Please fix the errors in your configuration file and try again.",
        file=sys.stderr,
    )
    sys.exit(1)
