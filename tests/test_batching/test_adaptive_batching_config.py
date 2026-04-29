#!/usr/bin/env python3

"""
Test suite for AdaptiveBatchingConfig Pydantic validation (UC-33..UC-42)
and new start_batch_size / start_batch_delay_sec fields (UT-A01..UT-A12).

These tests verify that the AdaptiveBatchingConfig schema correctly:
- Populates all 13 fields with default values
- Enforces strict min < max bounds for batch_size and batch_delay
- Validates start values within [min, max] bounds
- Rejects negative and zero values via gt=0 / ge=0 constraints
- Works as a default_factory within HealthPolicyConfig

UC-39 now tests the AdaptiveBatchController initialization with
start values from AdaptiveBatchingConfig.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import AdaptiveBatchingConfig, HealthPolicyConfig
from src.core.batching.adaptive import AdaptiveBatchController

# ---------------------------------------------------------------------------
# UT-A01: start_batch_size and start_batch_delay_sec defaults
# ---------------------------------------------------------------------------


def test_ut_a01_start_defaults():
    """
    UT-A01: start_batch_size defaults to 30 and start_batch_delay_sec defaults to 15.0.
    """
    cfg = AdaptiveBatchingConfig()
    assert cfg.start_batch_size == 30
    assert cfg.start_batch_delay_sec == 15.0


# ---------------------------------------------------------------------------
# UT-A02: start_batch_size below min_batch_size raises ValueError
# ---------------------------------------------------------------------------


def test_ut_a02_start_batch_size_below_min_raises():
    """
    UT-A02: start_batch_size=3 (< min_batch_size=5) should raise ValidationError
    from the model_validator bounds check.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_size=3)

    error_message = str(exc_info.value)
    assert "start_batch_size" in error_message


# ---------------------------------------------------------------------------
# UT-A03: start_batch_size above max_batch_size raises ValueError
# ---------------------------------------------------------------------------


def test_ut_a03_start_batch_size_above_max_raises():
    """
    UT-A03: start_batch_size=60 (> max_batch_size=50) should raise ValidationError
    from the model_validator bounds check.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_size=60)

    error_message = str(exc_info.value)
    assert "start_batch_size" in error_message


# ---------------------------------------------------------------------------
# UT-A04: start_batch_delay_sec below min_batch_delay_sec raises ValueError
# ---------------------------------------------------------------------------


def test_ut_a04_start_batch_delay_below_min_raises():
    """
    UT-A04: start_batch_delay_sec=1.0 (< min_batch_delay_sec=3.0) should raise
    ValidationError from the model_validator bounds check.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_delay_sec=1.0)

    error_message = str(exc_info.value)
    assert "start_batch_delay_sec" in error_message


# ---------------------------------------------------------------------------
# UT-A05: start_batch_delay_sec above max_batch_delay_sec raises ValueError
# ---------------------------------------------------------------------------


def test_ut_a05_start_batch_delay_above_max_raises():
    """
    UT-A05: start_batch_delay_sec=200.0 (> max_batch_delay_sec=120.0) should raise
    ValidationError from the model_validator bounds check.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_delay_sec=200.0)

    error_message = str(exc_info.value)
    assert "start_batch_delay_sec" in error_message


# ---------------------------------------------------------------------------
# UT-A06: start_batch_size within [min, max] is valid
# ---------------------------------------------------------------------------


def test_ut_a06_start_batch_size_within_bounds_valid():
    """
    UT-A06: start_batch_size=30 within [5, 50] is valid.
    """
    cfg = AdaptiveBatchingConfig(start_batch_size=30)
    assert cfg.start_batch_size == 30


# ---------------------------------------------------------------------------
# UT-A07: start_batch_delay_sec within [min, max] is valid
# ---------------------------------------------------------------------------


def test_ut_a07_start_batch_delay_within_bounds_valid():
    """
    UT-A07: start_batch_delay_sec=15.0 within [3.0, 120.0] is valid.
    """
    cfg = AdaptiveBatchingConfig(start_batch_delay_sec=15.0)
    assert cfg.start_batch_delay_sec == 15.0


# ---------------------------------------------------------------------------
# UT-A08: start_batch_size at min boundary is valid
# ---------------------------------------------------------------------------


def test_ut_a08_start_batch_size_at_min_valid():
    """
    UT-A08: start_batch_size=5 (== min_batch_size) is valid.
    The model_validator allows start in [min, max] inclusive.
    """
    cfg = AdaptiveBatchingConfig(start_batch_size=5)
    assert cfg.start_batch_size == 5


# ---------------------------------------------------------------------------
# UT-A09: start_batch_size at max boundary is valid
# ---------------------------------------------------------------------------


def test_ut_a09_start_batch_size_at_max_valid():
    """
    UT-A09: start_batch_size=50 (== max_batch_size) is valid.
    The model_validator allows start in [min, max] inclusive.
    """
    cfg = AdaptiveBatchingConfig(start_batch_size=50)
    assert cfg.start_batch_size == 50


# ---------------------------------------------------------------------------
# UT-A10: start_batch_delay_sec = 0 is valid per ge=0 field constraint
# ---------------------------------------------------------------------------


def test_ut_a10_start_batch_delay_sec_zero_ge0_valid():
    """
    UT-A10: start_batch_delay_sec=0 is valid per the ge=0 field constraint.

    DESIGN NOTE: With default min_batch_delay_sec=3.0 (gt=0 constraint),
    setting start_batch_delay_sec=0 fails the model_validator bounds check
    (0 < 3.0). To make the full config valid, min_batch_delay_sec must be
    <= 0, but min_batch_delay_sec has gt=0 which rejects 0.

    This test verifies that start_batch_delay_sec=0 does NOT trigger a
    ge=0 field-level error — the only validation failure comes from the
    model_validator bounds check, proving that the ge=0 constraint
    correctly allows 0 as a field value.

    If min_batch_delay_sec's constraint were changed from gt=0 to ge=0
    in src/config/schemas.py, then start_batch_delay_sec=0 could be
    used in a fully valid config.
    """
    # Attempt with start_batch_delay_sec=0 and default min_batch_delay_sec=3.0
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_delay_sec=0)

    errors = exc_info.value.errors()
    # Verify that there is NO field-level ge=0 error for start_batch_delay_sec
    start_delay_field_errors = [
        e for e in errors if e["loc"] == ("start_batch_delay_sec",)
    ]
    assert (
        len(start_delay_field_errors) == 0
    ), "start_batch_delay_sec=0 should NOT produce a ge=0 field-level error"
    # The error should be from the model_validator bounds check
    assert any("start_batch_delay_sec" in str(e.get("msg", "")) for e in errors)


# ---------------------------------------------------------------------------
# UT-A11: start_batch_delay_sec < 0 is invalid
# ---------------------------------------------------------------------------


def test_ut_a11_start_batch_delay_sec_negative_raises():
    """
    UT-A11: start_batch_delay_sec=-1.0 should raise ValidationError
    due to the ge=0 field constraint.
    """
    with pytest.raises(ValidationError) as exc_info:
        AdaptiveBatchingConfig(start_batch_delay_sec=-1.0)

    errors = exc_info.value.errors()
    # Verify there IS a field-level ge=0 error for start_batch_delay_sec
    start_delay_field_errors = [
        e for e in errors if e["loc"] == ("start_batch_delay_sec",)
    ]
    assert len(start_delay_field_errors) > 0
    assert start_delay_field_errors[0]["type"] == "greater_than_equal"


# ---------------------------------------------------------------------------
# UT-A12: Full AdaptiveBatchingConfig schema has 13 fields
# ---------------------------------------------------------------------------


def test_ut_a12_schema_has_13_fields():
    """
    UT-A12: AdaptiveBatchingConfig should have exactly 13 fields,
    including the new start_batch_size and start_batch_delay_sec.
    """
    field_names = list(AdaptiveBatchingConfig.model_fields.keys())
    assert len(field_names) == 13

    expected_fields = {
        "start_batch_size",
        "start_batch_delay_sec",
        "min_batch_size",
        "max_batch_size",
        "min_batch_delay_sec",
        "max_batch_delay_sec",
        "batch_size_step",
        "delay_step_sec",
        "rate_limit_divisor",
        "rate_limit_delay_multiplier",
        "recovery_threshold",
        "recovery_step_multiplier",
        "failure_rate_threshold",
    }
    assert set(field_names) == expected_fields


# ---------------------------------------------------------------------------
# UC-33: Valid config with defaults (updated with UT-H03)
# ---------------------------------------------------------------------------


def test_uc33_valid_config_with_defaults():
    """
    Creating AdaptiveBatchingConfig() without args should populate all 13
    fields with their documented default values.

    UT-H03: Added checks for start_batch_size == 30 and
    start_batch_delay_sec == 15.0.
    """
    cfg = AdaptiveBatchingConfig()

    # Start values (UT-H03)
    assert cfg.start_batch_size == 30
    assert cfg.start_batch_delay_sec == 15.0

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
#         (updated with UT-H04)
# ---------------------------------------------------------------------------


def test_uc38_default_factory_populated_in_health_policy():
    """
    Creating HealthPolicyConfig() without specifying adaptive_batching should
    populate it via default_factory with all default AdaptiveBatchingConfig values.

    UT-H04: Added checks for start_batch_size == 30 and
    start_batch_delay_sec == 15.0.
    """
    policy = HealthPolicyConfig()

    # Verify that adaptive_batching exists and is an AdaptiveBatchingConfig instance
    assert isinstance(policy.adaptive_batching, AdaptiveBatchingConfig)

    # Start values (UT-H04)
    assert policy.adaptive_batching.start_batch_size == 30
    assert policy.adaptive_batching.start_batch_delay_sec == 15.0

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
# UC-39: Controller initialization with start values (UT-H05)
# ---------------------------------------------------------------------------


def test_uc39_controller_initialization_with_start_values():
    """
    UT-H05: AdaptiveBatchingConfig(start_batch_size=20, start_batch_delay_sec=10.0)
    → create AdaptiveBatchController → verify batch_size=20, batch_delay=10.0.

    The controller now takes only config (no initial_batch_size/initial_batch_delay),
    and reads start values from config.start_batch_size and config.start_batch_delay_sec.
    """
    cfg = AdaptiveBatchingConfig(start_batch_size=20, start_batch_delay_sec=10.0)
    controller = AdaptiveBatchController(params=cfg.to_params())

    assert controller.batch_size == 20
    assert controller.batch_delay == 10.0


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
