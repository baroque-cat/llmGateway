#!/usr/bin/env python3

"""
Test suite for AdaptiveBatchingConfig Pydantic validation (UC-33..UC-42).

These tests verify that the AdaptiveBatchingConfig schema correctly:
- Populates all 11 fields with default values
- Enforces strict min < max bounds for batch_size and batch_delay
- Rejects negative and zero values via gt=0 / gt=1 constraints
- Works as a default_factory within HealthPolicyConfig

UC-39 is explicitly skipped — it is a controller-level (probe integration)
test, not a schema-level test.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import AdaptiveBatchingConfig, HealthPolicyConfig

# ---------------------------------------------------------------------------
# UC-33: Valid config with defaults
# ---------------------------------------------------------------------------


def test_uc33_valid_config_with_defaults():
    """
    Creating AdaptiveBatchingConfig() without args should populate all 11
    fields with their documented default values.
    """
    cfg = AdaptiveBatchingConfig()

    # Boundaries — batch size
    assert cfg.min_batch_size == 5
    assert cfg.max_batch_size == 50

    # Boundaries — delay
    assert cfg.min_batch_delay_sec == 3.0
    assert cfg.max_batch_delay_sec == 120.0

    # Additive step sizes
    assert cfg.batch_size_step == 5
    assert cfg.delay_step_sec == 2.0

    # Aggressive reaction to rate-limit (multiplicative)
    assert cfg.rate_limit_divisor == 2
    assert cfg.rate_limit_delay_multiplier == 2.0

    # Recovery tuning
    assert cfg.recovery_threshold == 5
    assert cfg.recovery_step_multiplier == 2.0

    # Threshold for moderate backoff on transient errors
    assert cfg.failure_rate_threshold == 0.3


# ---------------------------------------------------------------------------
# UC-34: min_batch_size < max_batch_size validation
# ---------------------------------------------------------------------------


def test_uc34_min_batch_size_greater_than_max_raises():
    """
    Passing min_batch_size=50, max_batch_size=10 should raise ValidationError
    because min must be strictly less than max (model_validator).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(min_batch_size=50, max_batch_size=10)

    error_message = str(exc_info.value)
    assert "min_batch_size" in error_message


# ---------------------------------------------------------------------------
# UC-35: min_batch_delay < max_batch_delay validation
# ---------------------------------------------------------------------------


def test_uc35_min_batch_delay_greater_than_max_raises():
    """
    Passing min_batch_delay=60.0, max_batch_delay=3.0 should raise ValidationError
    because min must be strictly less than max (model_validator).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(min_batch_delay_sec=60.0, max_batch_delay_sec=3.0)

    error_message = str(exc_info.value)
    assert "min_batch_delay_sec" in error_message


# ---------------------------------------------------------------------------
# UC-36: min_batch_size == max_batch_size validation (strictly less)
# ---------------------------------------------------------------------------


def test_uc36_min_batch_size_equals_max_raises():
    """
    Passing min_batch_size=30, max_batch_size=30 should raise ValidationError
    because min must be *strictly* less than max (>= is rejected).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(min_batch_size=30, max_batch_size=30)

    error_message = str(exc_info.value)
    assert "min_batch_size" in error_message


# ---------------------------------------------------------------------------
# UC-37: min_batch_delay == max_batch_delay validation (strictly less)
# ---------------------------------------------------------------------------


def test_uc37_min_batch_delay_equals_max_raises():
    """
    Passing min_batch_delay=15.0, max_batch_delay=15.0 should raise ValidationError
    because min must be *strictly* less than max (>= is rejected).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(min_batch_delay_sec=15.0, max_batch_delay_sec=15.0)

    error_message = str(exc_info.value)
    assert "min_batch_delay_sec" in error_message


# ---------------------------------------------------------------------------
# UC-38: default_factory populated when user doesn't specify adaptive_batching
# ---------------------------------------------------------------------------


def test_uc38_default_factory_populated_in_health_policy():
    """
    Creating HealthPolicyConfig() without specifying adaptive_batching should
    populate it via default_factory with all default AdaptiveBatchingConfig values.
    """
    policy = HealthPolicyConfig()

    # Verify that adaptive_batching exists and is an AdaptiveBatchingConfig instance
    assert isinstance(policy.adaptive_batching, AdaptiveBatchingConfig)

    # Verify all default values are populated
    assert policy.adaptive_batching.min_batch_size == 5
    assert policy.adaptive_batching.max_batch_size == 50
    assert policy.adaptive_batching.min_batch_delay_sec == 3.0
    assert policy.adaptive_batching.max_batch_delay_sec == 120.0
    assert policy.adaptive_batching.batch_size_step == 5
    assert policy.adaptive_batching.delay_step_sec == 2.0
    assert policy.adaptive_batching.rate_limit_divisor == 2
    assert policy.adaptive_batching.rate_limit_delay_multiplier == 2.0
    assert policy.adaptive_batching.recovery_threshold == 5
    assert policy.adaptive_batching.recovery_step_multiplier == 2.0
    assert policy.adaptive_batching.failure_rate_threshold == 0.3


# ---------------------------------------------------------------------------
# UC-39: SKIPPED — controller-level test, not schema-level
# ---------------------------------------------------------------------------


def test_uc39_skipped_controller_level_test():
    """
    UC-39 (existing batch_size/batch_delay_sec as initial values) is a
    controller-level test — it belongs to probes integration tests, not
    to the Pydantic config schema test suite. This scenario is explicitly
    skipped here.

    The AdaptiveBatchingConfig schema does not have initial_batch_size /
    initial_batch_delay fields — those are controller-level concepts that
    receive their initial values from HealthPolicyConfig.batch_size and
    HealthPolicyConfig.batch_delay_sec at runtime.
    """
    # Intentionally empty — this test documents the skip decision.
    pass


# ---------------------------------------------------------------------------
# UC-40: Negative values validation
# ---------------------------------------------------------------------------


def test_uc40_negative_min_batch_size_raises():
    """
    Passing min_batch_size=-1 should raise ValidationError due to gt=0 constraint.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(min_batch_size=-1)

    error_message = str(exc_info.value)
    assert "min_batch_size" in error_message


# ---------------------------------------------------------------------------
# UC-41: step_size and delay_step validation (gt=0)
# ---------------------------------------------------------------------------


def test_uc41_batch_size_step_zero_raises():
    """
    Passing batch_size_step=0 should raise ValidationError (gt=0 constraint).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(batch_size_step=0)

    error_message = str(exc_info.value)
    assert "batch_size_step" in error_message


def test_uc41_delay_step_sec_zero_raises():
    """
    Passing delay_step_sec=0.0 should raise ValidationError (gt=0 constraint).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(delay_step_sec=0.0)

    error_message = str(exc_info.value)
    assert "delay_step_sec" in error_message


# ---------------------------------------------------------------------------
# UC-42: recovery_threshold validation (gt=0)
# ---------------------------------------------------------------------------


def test_uc42_recovery_threshold_zero_raises():
    """
    Passing recovery_threshold=0 should raise ValidationError (gt=0 constraint).
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(recovery_threshold=0)

    error_message = str(exc_info.value)
    assert "recovery_threshold" in error_message


def test_uc42_recovery_threshold_five_is_valid():
    """
    Passing recovery_threshold=5 should be valid (gt=0 satisfied).
    """
    cfg = AdaptiveBatchingConfig(recovery_threshold=5)
    assert cfg.recovery_threshold == 5
