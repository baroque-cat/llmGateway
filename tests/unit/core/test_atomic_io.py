#!/usr/bin/env python3

"""Tests for atomic_io — write_atomic_ndjson pure function and module purity."""

import ast
import importlib
import json
import os
import pathlib
from unittest.mock import patch

import pytest

from src.core.atomic_io import write_atomic_ndjson

# ---------------------------------------------------------------------------
# 2.1: write_atomic_ndjson creates file with correct NDJSON content
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_creates_file_with_records(tmp_path: pathlib.Path) -> None:
    """write_atomic_ndjson(path, [{"a": 1}, {"b": 2}]) creates file with
    correct NDJSON content."""
    target = tmp_path / "output.ndjson"
    write_atomic_ndjson(str(target), [{"a": 1}, {"b": 2}])

    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}


# ---------------------------------------------------------------------------
# 2.2: Empty records creates empty file
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_empty_records_creates_empty_file(
    tmp_path: pathlib.Path,
) -> None:
    """write_atomic_ndjson(path, []) creates an empty file."""
    target = tmp_path / "empty.ndjson"
    write_atomic_ndjson(str(target), [])

    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content == ""


# ---------------------------------------------------------------------------
# 2.3: Non-existing parent dirs are created
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_creates_parent_dirs(tmp_path: pathlib.Path) -> None:
    """write_atomic_ndjson creates parent directories if they don't exist."""
    target = tmp_path / "deep" / "nested" / "dir" / "output.ndjson"
    # Ensure the parent dirs don't exist yet
    assert not target.parent.exists()

    write_atomic_ndjson(str(target), [{"x": 10}])

    assert target.parent.exists()
    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"x": 10}


# ---------------------------------------------------------------------------
# 2.4: Atomic replace — reader sees either old or new file (os.replace)
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_atomic_replace_no_partial(
    tmp_path: pathlib.Path,
) -> None:
    """write_atomic_ndjson uses os.replace for atomic swap — no partial file
    visible to readers."""
    target = tmp_path / "atomic.ndjson"

    # Write initial content so there's an "old" file
    write_atomic_ndjson(str(target), [{"old": True}])
    old_content = target.read_text(encoding="utf-8")

    # Patch os.replace to verify it is called (the atomic mechanism)
    with patch("src.core.atomic_io.os.replace", wraps=os.replace) as mock_replace:
        write_atomic_ndjson(str(target), [{"new": True}])

    # os.replace must have been called exactly once
    mock_replace.assert_called_once()

    # After the write, the file contains the new content — never partial
    new_content = target.read_text(encoding="utf-8")
    assert new_content != old_content
    assert json.loads(new_content.strip()) == {"new": True}


# ---------------------------------------------------------------------------
# 2.5: Temp file cleanup on error — target unchanged
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_temp_file_cleanup_on_error(
    tmp_path: pathlib.Path,
) -> None:
    """If an error occurs during write, the temp file is cleaned up and the
    target file remains unchanged."""
    target = tmp_path / "survives.ndjson"

    # Create target with initial content
    write_atomic_ndjson(str(target), [{"original": 1}])
    original_content = target.read_text(encoding="utf-8")

    # Collect temp files in the directory before the failing write
    before_tmp_files = set(tmp_path.glob("*.tmp"))

    # Force json.dumps to raise an exception
    with patch("src.core.atomic_io.json.dumps", side_effect=ValueError("forced")):
        with pytest.raises(ValueError, match="forced"):
            write_atomic_ndjson(str(target), [{"should_fail": True}])

    # Target file must still have original content
    assert target.read_text(encoding="utf-8") == original_content

    # No new .tmp files left behind
    after_tmp_files = set(tmp_path.glob("*.tmp"))
    assert after_tmp_files == before_tmp_files


# ---------------------------------------------------------------------------
# 2.6: Overwrites existing file
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_overwrites_existing_file(
    tmp_path: pathlib.Path,
) -> None:
    """write_atomic_ndjson overwrites an existing file with new content."""
    target = tmp_path / "overwrite.ndjson"

    # Write initial content
    write_atomic_ndjson(str(target), [{"first": "version"}])
    assert json.loads(target.read_text(encoding="utf-8").strip()) == {
        "first": "version"
    }

    # Overwrite with new content
    write_atomic_ndjson(str(target), [{"second": "version"}])
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"second": "version"}


# ---------------------------------------------------------------------------
# 2.7: Unicode characters preserved
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_preserves_unicode(tmp_path: pathlib.Path) -> None:
    """write_atomic_ndjson preserves Unicode characters in records."""
    target = tmp_path / "unicode.ndjson"
    records = [
        {"name": "日本語テスト", "emoji": "🎉🚀"},
        {"city": "München", "symbol": "Ω"},
    ]
    write_atomic_ndjson(str(target), records)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "日本語テスト"
    assert json.loads(lines[0])["emoji"] == "🎉🚀"
    assert json.loads(lines[1])["city"] == "München"
    assert json.loads(lines[1])["symbol"] == "Ω"


# ---------------------------------------------------------------------------
# 2.8: Module purity — only stdlib imports (tempfile, os, json, typing)
# ---------------------------------------------------------------------------


def test_atomic_io_module_no_non_stdlib_imports() -> None:
    """atomic_io.py imports only stdlib modules: tempfile, os, json, typing,
    logging, contextlib. No `from src.` imports or third-party libraries."""
    source_path = pathlib.Path(importlib.util.find_spec("src.core.atomic_io").origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    allowed_stdlib = {"tempfile", "os", "json", "typing", "logging", "contextlib"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level not in allowed_stdlib:
                    pytest.fail(
                        f"atomic_io.py imports non-allowed module: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            top_level = module_name.split(".")[0]
            # Reject src.* imports and non-stdlib imports
            if top_level.startswith("src"):
                pytest.fail(f"atomic_io.py imports from project module: {module_name}")
            if top_level not in allowed_stdlib:
                pytest.fail(
                    f"atomic_io.py imports from non-stdlib module: {module_name}"
                )


# ---------------------------------------------------------------------------
# 2.9: Single record
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_single_record(tmp_path: pathlib.Path) -> None:
    """write_atomic_ndjson with a single record produces exactly one line."""
    target = tmp_path / "single.ndjson"
    write_atomic_ndjson(str(target), [{"key": "value"}])

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"key": "value"}


# ---------------------------------------------------------------------------
# 2.10: Nested dict records
# ---------------------------------------------------------------------------


def test_write_atomic_ndjson_nested_dict_records(
    tmp_path: pathlib.Path,
) -> None:
    """write_atomic_ndjson correctly serializes nested dict records."""
    target = tmp_path / "nested.ndjson"
    records = [
        {"outer": {"inner_a": 1, "inner_b": [10, 20]}},
        {"metadata": {"tags": {"env": "prod", "region": "us"}}},
    ]
    write_atomic_ndjson(str(target), records)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"outer": {"inner_a": 1, "inner_b": [10, 20]}}
    assert json.loads(lines[1]) == {
        "metadata": {"tags": {"env": "prod", "region": "us"}}
    }
