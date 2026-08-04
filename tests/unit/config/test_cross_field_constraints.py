#!/usr/bin/env python3

"""
Test suite for cross-field constraint validation in Pydantic config schemas.

Group G6 tests: Cross-field constraints across HealthPolicyConfig, RetryPolicyConfig,
ErrorParsingRule, and ErrorParsingConfig.

These tests verify that model-level validators (@model_validator) and field-level
validators (@field_validator) correctly enforce relationships between multiple fields
within the same model.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    HealthPolicyConfig,
    KeySelectionConfig,
    PurgeConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import ErrorReason, KeySelectionMode

# ==============================================================================
# HealthPolicyConfig — verification_timeout constraint
#   task_timeout_sec >= verification_attempts * verification_delay_sec * 2
# ==============================================================================


def test_health_policy_task_timeout_sufficient_passes():
    """
    task_timeout_sec=900 with verification_attempts=3, verification_delay_sec=65.
    Required time = 3 × 65 × 2 = 390 ≤ 900 → passes.
    """
    config = HealthPolicyConfig(
        task_timeout_sec=900,
        verification_attempts=3,
        verification_delay_sec=65,
    )
    assert config.task_timeout_sec == 900
    assert config.verification_attempts == 3
    assert config.verification_delay_sec == 65


def test_health_policy_task_timeout_insufficient_rejected():
    """
    task_timeout_sec=300 with verification_attempts=10, verification_delay_sec=60.
    Required time = 10 × 60 × 2 = 1200 > 300 → rejected with ValidationError.
    """
    with pytest.raises(ValidationError, match="task_timeout_sec"):
        HealthPolicyConfig(
            task_timeout_sec=300,
            verification_attempts=10,
            verification_delay_sec=60,
        )


def test_health_policy_task_timeout_boundary_exact():
    """
    task_timeout_sec=390 with verification_attempts=3, verification_delay_sec=65.
    Required time = 3 × 65 × 2 = 390 ≤ 390 → passes (exact boundary).
    """
    config = HealthPolicyConfig(
        task_timeout_sec=390,
        verification_attempts=3,
        verification_delay_sec=65,
    )
    assert config.task_timeout_sec == 390


# ==============================================================================
# HealthPolicyConfig — quarantine_recheck vs stop_checking constraint
#   quarantine_recheck_interval_days < stop_checking_after_days (strictly less)
# ==============================================================================


def test_health_policy_quarantine_recheck_less_than_stop_checking_passes():
    """
    quarantine_recheck_interval_days=10, stop_checking_after_days=90.
    10 < 90 → passes.
    """
    config = HealthPolicyConfig(
        quarantine_recheck_interval_days=10,
        stop_checking_after_days=90,
    )
    assert config.quarantine_recheck_interval_days == 10
    assert config.stop_checking_after_days == 90


def test_health_policy_quarantine_recheck_equal_to_stop_checking_rejected():
    """
    quarantine_recheck_interval_days=90, stop_checking_after_days=90.
    90 >= 90 → rejected (must be strictly less).
    """
    with pytest.raises(ValidationError, match="quarantine_recheck_interval_days"):
        HealthPolicyConfig(
            quarantine_recheck_interval_days=90,
            stop_checking_after_days=90,
        )


def test_health_policy_quarantine_recheck_greater_than_stop_checking_rejected():
    """
    quarantine_recheck_interval_days=100, stop_checking_after_days=90.
    100 >= 90 → rejected.
    """
    with pytest.raises(ValidationError, match="quarantine_recheck_interval_days"):
        HealthPolicyConfig(
            quarantine_recheck_interval_days=100,
            stop_checking_after_days=90,
        )


# ==============================================================================
# RetryPolicyConfig — enabled vs attempts constraint
#   If enabled=True, at least one of on_key_error.attempts or
#   on_server_error.attempts must be >= 1.
# ==============================================================================


def test_retry_policy_enabled_with_attempts_passes():
    """
    enabled=True with on_key_error.attempts=3 → passes.
    At least one category has attempts >= 1.
    """
    config = RetryPolicyConfig(
        enabled=True,
        on_key_error=RetryOnErrorConfig(attempts=3),
    )
    assert config.enabled is True
    assert config.on_key_error.attempts == 3


def test_retry_policy_enabled_without_any_attempts_rejected():
    """
    enabled=True with default attempts=0 in both sub-categories → rejected.
    Neither on_key_error nor on_server_error has attempts >= 1.
    """
    with pytest.raises(ValidationError, match="retry.enabled"):
        RetryPolicyConfig(enabled=True)


def test_retry_policy_enabled_with_only_server_attempts_passes():
    """
    enabled=True with only on_server_error.attempts=2 → passes.
    At least one category (server_error) has attempts >= 1.

    NOTE: This test covers the NON-sticky (round_robin) case whose behavior is
    preserved. Design D5 changes the rule only for sticky mode — when
    key_selection.mode is 'sticky', on_key_error.attempts must be >= 1
    regardless of on_server_error.attempts (see
    test_sticky_retry_without_key_error_attempts_rejected below).
    """
    config = RetryPolicyConfig(
        enabled=True,
        on_server_error=RetryOnErrorConfig(attempts=2),
    )
    assert config.enabled is True
    assert config.on_server_error.attempts == 2


def test_retry_policy_disabled_without_attempts_passes():
    """
    enabled=False with default attempts=0 → passes.
    When retry is disabled, attempts are irrelevant.
    """
    config = RetryPolicyConfig(enabled=False)
    assert config.enabled is False
    assert config.on_key_error.attempts == 0
    assert config.on_server_error.attempts == 0


# ==============================================================================
# GatewayPolicyConfig — sticky-mode retry constraint (design D5)
#   When key_selection.mode is 'sticky' and retry.enabled is true,
#   on_key_error.attempts MUST be >= 1.  on_server_error.attempts alone does
#   NOT satisfy the requirement because sticky retry rotates the key on every
#   trigger and never executes the same-key on_server_error branch.
# ==============================================================================


def test_sticky_retry_without_key_error_attempts_rejected():
    """
    Sticky mode + retry.enabled=true + on_key_error.attempts=0 → ValidationError.

    Design D5: in sticky mode, the retry loop rotates the key on every trigger
    and ignores on_server_error, so on_key_error.attempts must be >= 1.
    """
    with pytest.raises(ValidationError, match="on_key_error"):
        GatewayPolicyConfig(
            key_selection=KeySelectionConfig(mode=KeySelectionMode.STICKY),
            retry=RetryPolicyConfig(
                enabled=True,
                on_key_error=RetryOnErrorConfig(attempts=0),
            ),
        )


def test_sticky_retry_with_only_server_error_attempts_rejected():
    """
    Sticky mode + retry.enabled=true + only on_server_error.attempts=5 →
    ValidationError.  on_server_error.attempts alone does NOT satisfy the
    requirement in sticky mode.
    """
    with pytest.raises(ValidationError, match="on_key_error"):
        GatewayPolicyConfig(
            key_selection=KeySelectionConfig(mode=KeySelectionMode.STICKY),
            retry=RetryPolicyConfig(
                enabled=True,
                on_key_error=RetryOnErrorConfig(attempts=0),
                on_server_error=RetryOnErrorConfig(attempts=5),
            ),
        )


def test_sticky_retry_with_key_error_attempts_passes():
    """
    Sticky mode + retry.enabled=true + on_key_error.attempts=3 → passes.
    on_key_error.attempts >= 1 satisfies the sticky-mode requirement.
    """
    config = GatewayPolicyConfig(
        key_selection=KeySelectionConfig(mode=KeySelectionMode.STICKY),
        retry=RetryPolicyConfig(
            enabled=True,
            on_key_error=RetryOnErrorConfig(attempts=3),
        ),
    )
    assert config.key_selection.mode is KeySelectionMode.STICKY
    assert config.retry.enabled is True
    assert config.retry.on_key_error.attempts == 3


def test_round_robin_retry_with_only_server_error_attempts_passes():
    """
    Round-robin mode + retry.enabled=true + only on_server_error.attempts=5 →
    passes.  The sticky constraint does NOT apply to round_robin mode — only
    the generic RetryPolicyConfig validator runs, and it accepts
    on_server_error.attempts >= 1.
    """
    config = GatewayPolicyConfig(
        key_selection=KeySelectionConfig(mode=KeySelectionMode.ROUND_ROBIN),
        retry=RetryPolicyConfig(
            enabled=True,
            on_server_error=RetryOnErrorConfig(attempts=5),
        ),
    )
    assert config.key_selection.mode is KeySelectionMode.ROUND_ROBIN
    assert config.retry.enabled is True
    assert config.retry.on_server_error.attempts == 5


# ==============================================================================
# ErrorParsingRule — match_pattern regex validation
#   match_pattern must be a valid compilable regular expression.
# ==============================================================================


def test_error_parsing_rule_valid_regex_passes():
    """
    match_pattern="INVALID_ARGUMENT" (valid literal regex) → passes.
    """
    rule = ErrorParsingRule(
        status_code=400,
        error_path="error.type",
        match_pattern="INVALID_ARGUMENT",
        map_to=ErrorReason.INVALID_KEY,
    )
    assert rule.match_pattern == "INVALID_ARGUMENT"


def test_error_parsing_rule_invalid_regex_rejected():
    """
    match_pattern="(unclosed" (invalid regex: unclosed parenthesis) → rejected
    with ValidationError from @field_validator.
    """
    with pytest.raises(ValidationError, match="match_pattern"):
        ErrorParsingRule(
            status_code=400,
            error_path="error.type",
            match_pattern="(unclosed",
            map_to=ErrorReason.INVALID_KEY,
        )


# ==============================================================================
# ErrorParsingConfig — unique priorities per status_code constraint
#   Within each status_code group, all rule priority values must be unique.
# ==============================================================================


def test_error_parsing_config_unique_priorities_per_status_code_passes():
    """
    Two rules with status_code=400 but different priorities (10 and 5) → passes.
    Priorities are unique within the same status_code group.
    """
    config = ErrorParsingConfig(
        rules=[
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="INVALID_ARGUMENT",
                map_to=ErrorReason.INVALID_KEY,
                priority=10,
            ),
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="NO_QUOTA",
                map_to=ErrorReason.NO_QUOTA,
                priority=5,
            ),
        ]
    )
    assert len(config.rules) == 2


def test_error_parsing_config_duplicate_priorities_per_status_code_rejected():
    """
    Two rules with status_code=400 and same priority=10 → rejected with ValidationError.
    Duplicate priority within the same status_code group.
    """
    with pytest.raises(ValidationError, match="Duplicate priority"):
        ErrorParsingConfig(
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="INVALID_ARGUMENT",
                    map_to=ErrorReason.INVALID_KEY,
                    priority=10,
                ),
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.code",
                    match_pattern="RATE_LIMITED",
                    map_to=ErrorReason.RATE_LIMITED,
                    priority=10,
                ),
            ]
        )


def test_error_parsing_config_different_status_codes_same_priority_passes():
    """
    Two rules with different status_codes (400 and 429) but same priority=10 → passes.
    Same priority is allowed across different status_code groups.
    """
    config = ErrorParsingConfig(
        rules=[
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="INVALID_ARGUMENT",
                map_to=ErrorReason.INVALID_KEY,
                priority=10,
            ),
            ErrorParsingRule(
                status_code=429,
                error_path="error.type",
                match_pattern="RATE_LIMITED",
                map_to=ErrorReason.RATE_LIMITED,
                priority=10,
            ),
        ]
    )
    assert len(config.rules) == 2


# ==============================================================================
# HealthPolicyConfig — purge.after_days minimum constraint
#   purge.after_days >= stop_checking_after_days + amnesty_threshold_days + 7
# ==============================================================================


def test_health_policy_purge_after_days_meets_minimum_passes():
    """
    M1: purge.after_days=180, stop_checking_after_days=90, amnesty_threshold_days=2.0.
    Minimum = 90 + 2.0 + 7 = 99.0. 180 >= 99 → passes.
    """
    config = HealthPolicyConfig(
        purge=PurgeConfig(after_days=180),
        stop_checking_after_days=90,
        amnesty_threshold_days=2.0,
    )
    assert config.purge.after_days == 180


def test_health_policy_purge_after_days_below_minimum_rejected():
    """
    M2: purge.after_days=90, stop_checking_after_days=90, amnesty_threshold_days=2.0.
    Minimum = 90 + 2.0 + 7 = 99.0. 90 < 99 → rejected with ValidationError
    containing "must be >= 99" (or equivalent message about the minimum).
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(
            purge=PurgeConfig(after_days=90),
            stop_checking_after_days=90,
            amnesty_threshold_days=2.0,
        )

    error_message = str(exc_info.value)
    # The validator raises ValueError with message containing the computed minimum
    assert "99" in error_message


def test_health_policy_purge_after_days_exact_boundary_passes():
    """
    M3: purge.after_days=99, stop_checking_after_days=90, amnesty_threshold_days=2.0.
    Minimum = 90 + 2.0 + 7 = 99.0. 99 >= 99 → passes (exact boundary).
    """
    config = HealthPolicyConfig(
        purge=PurgeConfig(after_days=99),
        stop_checking_after_days=90,
        amnesty_threshold_days=2.0,
    )
    assert config.purge.after_days == 99


def test_health_policy_purge_after_days_one_below_boundary_rejected():
    """
    M4: purge.after_days=98, stop_checking_after_days=90, amnesty_threshold_days=2.0.
    Minimum = 90 + 2.0 + 7 = 99.0. 98 < 99 → rejected with ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(
            purge=PurgeConfig(after_days=98),
            stop_checking_after_days=90,
            amnesty_threshold_days=2.0,
        )

    error_message = str(exc_info.value)
    assert "99" in error_message
