#!/usr/bin/env python3

"""Tests for KeyCircuitBreaker purity —
no config imports in src/core/breaker/, imports CircuitBreakerParams from core.models.
"""

import ast
import importlib
import pathlib

import pytest

# ---------------------------------------------------------------------------
# Purity — no config imports in breaker module
# ---------------------------------------------------------------------------


def test_breaker_no_config_imports() -> None:
    """circuit_breaker.py does not import from src.config."""
    source_path = pathlib.Path(
        importlib.util.find_spec("src.core.breaker.circuit_breaker").origin
    )
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = getattr(node, "module", "") or ""
            if module_name.startswith("src.config"):
                pytest.fail(
                    f"circuit_breaker.py imports from config layer: {module_name}"
                )


# ---------------------------------------------------------------------------
# Purity — imports CircuitBreakerParams from core.models
# ---------------------------------------------------------------------------


def test_breaker_imports_params_from_core_models() -> None:
    """circuit_breaker.py imports CircuitBreakerParams from src.core.models."""
    source_path = pathlib.Path(
        importlib.util.find_spec("src.core.breaker.circuit_breaker").origin
    )
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.core.models":
            for alias in node.names:
                if alias.name == "CircuitBreakerParams":
                    found = True
                    break
    assert found, (
        "circuit_breaker.py does not import CircuitBreakerParams "
        "from src.core.models"
    )
