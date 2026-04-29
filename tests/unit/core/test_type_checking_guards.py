#!/usr/bin/env python3

"""Tests for TYPE_CHECKING guards in interfaces.py and probes.py —
DatabaseManager is only imported under TYPE_CHECKING, not at runtime."""

import ast
import importlib
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Helper: parse a module's source and check for TYPE_CHECKING guard
# ---------------------------------------------------------------------------


def _has_type_checking_guard(module_name: str, guarded_import: str) -> bool:
    """Return True if the module source contains an `if TYPE_CHECKING:` block
    that imports the specified module path."""
    source_path = pathlib.Path(importlib.util.find_spec(module_name).origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Check if the test is `TYPE_CHECKING`
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            for child in node.body:
                if isinstance(child, ast.ImportFrom):
                    if guarded_import in (child.module or ""):
                        return True
    return False


def _has_future_annotations(module_name: str) -> bool:
    """Return True if the module source contains `from __future__ import annotations`."""
    source_path = pathlib.Path(importlib.util.find_spec(module_name).origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            for alias in node.names:
                if alias.name == "annotations":
                    return True
    return False


def _module_source_text(module_name: str) -> str:
    source_path = pathlib.Path(importlib.util.find_spec(module_name).origin)
    return source_path.read_text()


# ---------------------------------------------------------------------------
# 2.4-a: No runtime DatabaseManager import in interfaces.py
# ---------------------------------------------------------------------------


def test_interfaces_no_runtime_db_import() -> None:
    """Importing interfaces.py does not import DatabaseManager at runtime."""
    # Strategy: Check that 'src.db.database' is not in sys.modules after import.
    # First, remove it if already loaded (from other tests).
    pre_existing = "src.db.database" in sys.modules
    if pre_existing:
        # We can't fully unload, so use source analysis instead
        source = _module_source_text("src.core.interfaces")
        # Any import of DatabaseManager outside a TYPE_CHECKING block
        # would appear as a top-level ImportFrom without a guard.
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                if "src.db" in (node.module or ""):
                    for alias in node.names:
                        if alias.name == "DatabaseManager":
                            pytest.fail(
                                "interfaces.py has a top-level (runtime) "
                                "import of DatabaseManager from src.db"
                            )
    else:
        import src.core.interfaces  # noqa: F401

        assert (
            "src.db.database" not in sys.modules
        ), "src.db.database was imported at runtime by src.core.interfaces"


# ---------------------------------------------------------------------------
# 2.4-b: No runtime DatabaseManager import in probes.py
# ---------------------------------------------------------------------------


def test_probes_no_runtime_db_import() -> None:
    """Importing probes.py does not import DatabaseManager at runtime."""
    source = _module_source_text("src.core.probes")
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            if "src.db" in (node.module or ""):
                for alias in node.names:
                    if alias.name == "DatabaseManager":
                        pytest.fail(
                            "probes.py has a top-level (runtime) "
                            "import of DatabaseManager from src.db"
                        )


# ---------------------------------------------------------------------------
# 2.4-c: interfaces.py has future annotations
# ---------------------------------------------------------------------------


def test_interfaces_has_future_annotations() -> None:
    """interfaces.py contains 'from __future__ import annotations'."""
    assert _has_future_annotations(
        "src.core.interfaces"
    ), "interfaces.py missing 'from __future__ import annotations'"


# ---------------------------------------------------------------------------
# 2.4-d: probes.py has future annotations
# ---------------------------------------------------------------------------


def test_probes_has_future_annotations() -> None:
    """probes.py contains 'from __future__ import annotations'."""
    assert _has_future_annotations(
        "src.core.probes"
    ), "probes.py missing 'from __future__ import annotations'"


# ---------------------------------------------------------------------------
# 2.4-e: interfaces.py TYPE_CHECKING guard exists
# ---------------------------------------------------------------------------


def test_interfaces_type_checking_guard_exists() -> None:
    """interfaces.py contains 'if TYPE_CHECKING:' block with DatabaseManager."""
    assert _has_type_checking_guard(
        "src.core.interfaces", "src.db.database"
    ), "interfaces.py missing TYPE_CHECKING guard for DatabaseManager"


# ---------------------------------------------------------------------------
# 2.4-f: probes.py TYPE_CHECKING guard exists
# ---------------------------------------------------------------------------


def test_probes_type_checking_guard_exists() -> None:
    """probes.py contains 'if TYPE_CHECKING:' block with DatabaseManager."""
    assert _has_type_checking_guard(
        "src.core.probes", "src.db.database"
    ), "probes.py missing TYPE_CHECKING guard for DatabaseManager"
