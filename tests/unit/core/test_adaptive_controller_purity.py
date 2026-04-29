#!/usr/bin/env python3

"""Tests for AdaptiveBatchController purity and constructor contract —
no config imports, accepts only params kwarg, start values clamped."""

import ast
import importlib
import pathlib

import pytest

from src.core.batching.adaptive import AdaptiveBatchController
from src.core.models import AdaptiveBatchingParams

# ---------------------------------------------------------------------------
# Helper: create a valid params instance for tests
# ---------------------------------------------------------------------------


def _make_params(**overrides: int | float) -> AdaptiveBatchingParams:
    """Create an AdaptiveBatchingParams with sensible defaults, allowing overrides."""
    defaults = {
        "start_batch_size": 10,
        "start_batch_delay_sec": 5.0,
        "min_batch_size": 1,
        "max_batch_size": 100,
        "min_batch_delay_sec": 1.0,
        "max_batch_delay_sec": 60.0,
        "batch_size_step": 5,
        "delay_step_sec": 2.0,
        "rate_limit_divisor": 2,
        "rate_limit_delay_multiplier": 2.0,
        "recovery_threshold": 3,
        "recovery_step_multiplier": 2.0,
        "failure_rate_threshold": 0.3,
    }
    defaults.update(overrides)
    return AdaptiveBatchingParams(**defaults)


# ---------------------------------------------------------------------------
# 2.5-a: Purity — no config imports in adaptive.py
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
# 2.5-b: Purity — imports AdaptiveBatchingParams from core.models
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


# ---------------------------------------------------------------------------
# 2.6-a: Constructor accepts only `params` kwarg
# ---------------------------------------------------------------------------


def test_controller_accepts_only_params_kwarg() -> None:
    """AdaptiveBatchController(params=valid_params) works."""
    params = _make_params()
    controller = AdaptiveBatchController(params=params)
    assert controller.batch_size == 10  # start_batch_size within bounds


# ---------------------------------------------------------------------------
# 2.6-b: Constructor rejects `config` kwarg
# ---------------------------------------------------------------------------


def test_controller_rejects_config_kwarg() -> None:
    """AdaptiveBatchController(config=xxx) raises TypeError."""
    with pytest.raises(TypeError):
        AdaptiveBatchController(config=_make_params())  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2.6-c: Start values clamped at construction
# ---------------------------------------------------------------------------


def test_controller_start_values_capped_at_construction() -> None:
    """start_batch_size=100, max_batch_size=50 → batch_size==50."""
    params = _make_params(start_batch_size=100, max_batch_size=50)
    controller = AdaptiveBatchController(params=params)
    assert controller.batch_size == 50


# ---------------------------------------------------------------------------
# 2.6-d: Controller initializes from params
# ---------------------------------------------------------------------------


def test_controller_initializes_from_params() -> None:
    """Controller reads start values and boundaries from params correctly."""
    params = _make_params(
        start_batch_size=20,
        start_batch_delay_sec=10.0,
        min_batch_size=5,
        max_batch_size=80,
        min_batch_delay_sec=2.0,
        max_batch_delay_sec=50.0,
    )
    controller = AdaptiveBatchController(params=params)

    # start_batch_size=20 is within [5, 80] → should be 20
    assert controller.batch_size == 20
    # start_batch_delay_sec=10.0 is within [2.0, 50.0] → should be 10.0
    assert controller.batch_delay == 10.0
