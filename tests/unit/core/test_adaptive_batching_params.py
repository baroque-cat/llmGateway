#!/usr/bin/env python3

"""Tests for AdaptiveBatchingParams frozen dataclass — field count, types,
immutability, and absence of Pydantic dependency."""

import ast
import dataclasses
import importlib
import pathlib

import pytest

from src.core.models import AdaptiveBatchingParams

# ---------------------------------------------------------------------------
# 2.2-a: Field count
# ---------------------------------------------------------------------------


def test_params_has_13_fields() -> None:
    """dataclasses.fields(AdaptiveBatchingParams) returns 13 elements."""
    fields = dataclasses.fields(AdaptiveBatchingParams)
    assert len(fields) == 13


# ---------------------------------------------------------------------------
# 2.2-b: Field types
# ---------------------------------------------------------------------------

# Expected field name → type mapping
_EXPECTED_FIELD_TYPES: dict[str, type] = {
    "start_batch_size": int,
    "start_batch_delay_sec": float,
    "min_batch_size": int,
    "max_batch_size": int,
    "min_batch_delay_sec": float,
    "max_batch_delay_sec": float,
    "batch_size_step": int,
    "delay_step_sec": float,
    "rate_limit_divisor": int,
    "rate_limit_delay_multiplier": float,
    "recovery_threshold": int,
    "recovery_step_multiplier": float,
    "failure_rate_threshold": float,
}


def test_params_field_types() -> None:
    """Field types are int or float as specified."""
    fields = dataclasses.fields(AdaptiveBatchingParams)
    for field in fields:
        expected = _EXPECTED_FIELD_TYPES[field.name]
        assert field.type is expected, (
            f"Field '{field.name}' expected {expected.__name__}, "
            f"got {field.type.__name__ if isinstance(field.type, type) else field.type}"
        )


# ---------------------------------------------------------------------------
# 2.2-c: Frozen / immutability
# ---------------------------------------------------------------------------


def test_params_frozen_immutable() -> None:
    """Assigning to a field raises FrozenInstanceError."""
    params = AdaptiveBatchingParams(
        start_batch_size=10,
        start_batch_delay_sec=5.0,
        min_batch_size=1,
        max_batch_size=100,
        min_batch_delay_sec=1.0,
        max_batch_delay_sec=60.0,
        batch_size_step=5,
        delay_step_sec=2.0,
        rate_limit_divisor=2,
        rate_limit_delay_multiplier=2.0,
        recovery_threshold=3,
        recovery_step_multiplier=2.0,
        failure_rate_threshold=0.3,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.start_batch_size = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2.2-d: Requires all 13 fields
# ---------------------------------------------------------------------------


def test_params_requires_all_13_fields() -> None:
    """Creating with a missing field raises TypeError."""
    # Omit 'failure_rate_threshold'
    with pytest.raises(TypeError):
        AdaptiveBatchingParams(
            start_batch_size=10,
            start_batch_delay_sec=5.0,
            min_batch_size=1,
            max_batch_size=100,
            min_batch_delay_sec=1.0,
            max_batch_delay_sec=60.0,
            batch_size_step=5,
            delay_step_sec=2.0,
            rate_limit_divisor=2,
            rate_limit_delay_multiplier=2.0,
            recovery_threshold=3,
            recovery_step_multiplier=2.0,
            # failure_rate_threshold omitted
        )


# ---------------------------------------------------------------------------
# 2.2-e: All fields accessible
# ---------------------------------------------------------------------------


def test_params_all_fields_accessible() -> None:
    """All 13 attributes are accessible on a constructed instance."""
    params = AdaptiveBatchingParams(
        start_batch_size=10,
        start_batch_delay_sec=5.0,
        min_batch_size=1,
        max_batch_size=100,
        min_batch_delay_sec=1.0,
        max_batch_delay_sec=60.0,
        batch_size_step=5,
        delay_step_sec=2.0,
        rate_limit_divisor=2,
        rate_limit_delay_multiplier=2.0,
        recovery_threshold=3,
        recovery_step_multiplier=2.0,
        failure_rate_threshold=0.3,
    )
    for name in _EXPECTED_FIELD_TYPES:
        assert hasattr(params, name), f"Missing attribute: {name}"
        # Verify the value is accessible
        getattr(params, name)


# ---------------------------------------------------------------------------
# 2.2-f: No Pydantic dependency
# ---------------------------------------------------------------------------


def test_params_no_pydantic_dependency() -> None:
    """core/models.py has no 'from pydantic' import."""
    source_path = pathlib.Path(importlib.util.find_spec("src.core.models").origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = getattr(node, "module", "") or ""
            if "pydantic" in module_name:
                pytest.fail(f"core/models.py imports from pydantic: {module_name}")
