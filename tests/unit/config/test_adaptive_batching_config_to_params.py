#!/usr/bin/env python3

"""Tests for AdaptiveBatchingConfig.to_params() — conversion from Pydantic
model to frozen dataclass preserves all values."""

import dataclasses

import pytest

from src.config.schemas import AdaptiveBatchingConfig
from src.core.models import AdaptiveBatchingParams

# ---------------------------------------------------------------------------
# 2.3-a: Returns correct type
# ---------------------------------------------------------------------------


def test_to_params_returns_correct_type() -> None:
    """isinstance(config.to_params(), AdaptiveBatchingParams)."""
    config = AdaptiveBatchingConfig()
    result = config.to_params()
    assert isinstance(result, AdaptiveBatchingParams)


# ---------------------------------------------------------------------------
# 2.3-b: Result is frozen
# ---------------------------------------------------------------------------


def test_to_params_result_is_frozen() -> None:
    """Result is frozen — FrozenInstanceError on mutation."""
    config = AdaptiveBatchingConfig()
    result = config.to_params()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.start_batch_size = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2.3-c: Preserves all field values
# ---------------------------------------------------------------------------


def test_to_params_preserves_all_field_values() -> None:
    """All 13 values match between config and params."""
    config = AdaptiveBatchingConfig()
    params = config.to_params()

    param_fields = dataclasses.fields(AdaptiveBatchingParams)
    for field in param_fields:
        config_val = getattr(config, field.name)
        params_val = getattr(params, field.name)
        assert (
            config_val == params_val
        ), f"Field '{field.name}': config={config_val}, params={params_val}"


# ---------------------------------------------------------------------------
# 2.3-d: Custom values preserved
# ---------------------------------------------------------------------------


def test_to_params_with_custom_values() -> None:
    """Custom non-default values are preserved through conversion."""
    config = AdaptiveBatchingConfig(
        start_batch_size=25,
        start_batch_delay_sec=10.0,
        min_batch_size=3,
        max_batch_size=80,
        min_batch_delay_sec=2.0,
        max_batch_delay_sec=90.0,
        batch_size_step=7,
        delay_step_sec=3.0,
        rate_limit_divisor=3,
        rate_limit_delay_multiplier=1.5,
        recovery_threshold=4,
        recovery_step_multiplier=1.8,
        failure_rate_threshold=0.25,
    )
    params = config.to_params()

    assert params.start_batch_size == 25
    assert params.start_batch_delay_sec == 10.0
    assert params.min_batch_size == 3
    assert params.max_batch_size == 80
    assert params.min_batch_delay_sec == 2.0
    assert params.max_batch_delay_sec == 90.0
    assert params.batch_size_step == 7
    assert params.delay_step_sec == 3.0
    assert params.rate_limit_divisor == 3
    assert params.rate_limit_delay_multiplier == 1.5
    assert params.recovery_threshold == 4
    assert params.recovery_step_multiplier == 1.8
    assert params.failure_rate_threshold == 0.25


# ---------------------------------------------------------------------------
# 2.3-e: Default values work
# ---------------------------------------------------------------------------


def test_to_params_with_default_values() -> None:
    """Default values from AdaptiveBatchingConfig are correctly converted."""
    config = AdaptiveBatchingConfig()
    params = config.to_params()

    # Check a representative subset of defaults
    assert params.start_batch_size == 30
    assert params.start_batch_delay_sec == 15.0
    assert params.min_batch_size == 5
    assert params.max_batch_size == 50
    assert params.failure_rate_threshold == 0.3
