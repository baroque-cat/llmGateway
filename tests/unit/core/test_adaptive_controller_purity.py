#!/usr/bin/env python3

"""Tests for AdaptiveBatchController purity —
no config imports, imports AdaptiveBatchingParams from core.models."""

import ast
import importlib
import pathlib

import pytest

# ---------------------------------------------------------------------------
# Purity — no config imports in adaptive.py
# ---------------------------------------------------------------------------


def test_adaptive_no_config_imports() -> None:
    """adaptive.py does not import from src.config."""
    source_path = pathlib.Path(
        importlib.util.find_spec("src.core.batching.adaptive").origin
    )
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = getattr(node, "module", "") or ""
            if module_name.startswith("src.config"):
                pytest.fail(f"adaptive.py imports from config layer: {module_name}")


# ---------------------------------------------------------------------------
# Purity — imports AdaptiveBatchingParams from core.models
# ---------------------------------------------------------------------------


def test_adaptive_imports_params_from_core_models() -> None:
    """adaptive.py imports AdaptiveBatchingParams from src.core.models."""
    source_path = pathlib.Path(
        importlib.util.find_spec("src.core.batching.adaptive").origin
    )
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.core.models":
            for alias in node.names:
                if alias.name == "AdaptiveBatchingParams":
                    found = True
                    break
    assert (
        found
    ), "adaptive.py does not import AdaptiveBatchingParams from src.core.models"
