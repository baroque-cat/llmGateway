#!/usr/bin/env python3

"""
Tests for CircuitBreakerConfig and BackoffConfig validation —
enum members, numeric field constraints, and cross-field validators.

Covers the 16 scenarios defined in the harden-config-validation test plan (G4).
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import BackoffConfig, CircuitBreakerConfig
from src.core.constants import CircuitBreakerMode

# ---------------------------------------------------------------------------
# CircuitBreakerMode enum
# ---------------------------------------------------------------------------


class TestCircuitBreakerModeEnum:
    """Validate CircuitBreakerMode enum definition."""

    def test_circuit_breaker_mode_enum_members(self) -> None:
        """list(CircuitBreakerMode) == [AUTO_RECOVERY, MANUAL_RESET];
        values are 'auto_recovery' and 'manual_reset'."""
        members = list(CircuitBreakerMode)
        assert len(members) == 2
        assert members[0] == CircuitBreakerMode.AUTO_RECOVERY
        assert members[1] == CircuitBreakerMode.MANUAL_RESET
        assert CircuitBreakerMode.AUTO_RECOVERY.value == "auto_recovery"
        assert CircuitBreakerMode.MANUAL_RESET.value == "manual_reset"


# ---------------------------------------------------------------------------
# CircuitBreakerConfig — mode field
# ---------------------------------------------------------------------------


class TestCircuitBreakerConfigMode:
    """Validate CircuitBreakerConfig mode enum coercion and rejection."""

    def test_circuit_breaker_config_valid_mode_auto_recovery(self) -> None:
        """CircuitBreakerConfig(mode='auto_recovery') → mode == CircuitBreakerMode.AUTO_RECOVERY."""
        cfg = CircuitBreakerConfig(mode="auto_recovery")
        assert cfg.mode == CircuitBreakerMode.AUTO_RECOVERY

    def test_circuit_breaker_config_valid_mode_manual_reset(self) -> None:
        """CircuitBreakerConfig(mode='manual_reset') → mode == CircuitBreakerMode.MANUAL_RESET."""
        cfg = CircuitBreakerConfig(mode="manual_reset")
        assert cfg.mode == CircuitBreakerMode.MANUAL_RESET

    def test_circuit_breaker_config_invalid_mode_rejected(self) -> None:
        """CircuitBreakerConfig(mode='half_open') → ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(mode="half_open")
        # The error message should reference the valid enum values.
        errors = exc_info.value.errors()
        assert any(
            "auto_recovery" in str(e) or "manual_reset" in str(e) for e in errors
        )

    def test_circuit_breaker_config_default_mode(self) -> None:
        """CircuitBreakerConfig() → mode defaults to AUTO_RECOVERY."""
        cfg = CircuitBreakerConfig()
        assert cfg.mode == CircuitBreakerMode.AUTO_RECOVERY


# ---------------------------------------------------------------------------
# CircuitBreakerConfig — numeric field constraints
# ---------------------------------------------------------------------------


class TestCircuitBreakerNumericConstraints:
    """Validate failure_threshold (gt=0) and jitter_sec (ge=0)."""

    def test_circuit_breaker_failure_threshold_zero_rejected(self) -> None:
        """CircuitBreakerConfig(failure_threshold=0) → ValidationError (gt=0)."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(failure_threshold=0)
        errors = exc_info.value.errors()
        assert any("greater than 0" in str(e) for e in errors)

    def test_circuit_breaker_failure_threshold_negative_rejected(self) -> None:
        """CircuitBreakerConfig(failure_threshold=-5) → ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(failure_threshold=-5)
        errors = exc_info.value.errors()
        assert any("greater than 0" in str(e) for e in errors)

    def test_circuit_breaker_jitter_sec_negative_rejected(self) -> None:
        """CircuitBreakerConfig(jitter_sec=-1) → ValidationError (ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(jitter_sec=-1)
        errors = exc_info.value.errors()
        assert any("greater than or equal to 0" in str(e) for e in errors)

    def test_circuit_breaker_jitter_sec_zero_valid(self) -> None:
        """CircuitBreakerConfig(jitter_sec=0) → passes (ge=0 allows zero)."""
        cfg = CircuitBreakerConfig(jitter_sec=0)
        assert cfg.jitter_sec == 0


# ---------------------------------------------------------------------------
# BackoffConfig — numeric field constraints
# ---------------------------------------------------------------------------


class TestBackoffNumericConstraints:
    """Validate base_duration_sec (gt=0), max_duration_sec (gt=0), factor (ge=1.0)."""

    def test_backoff_config_base_duration_zero_rejected(self) -> None:
        """BackoffConfig(base_duration_sec=0) → ValidationError (gt=0)."""
        with pytest.raises(ValidationError) as exc_info:
            BackoffConfig(base_duration_sec=0)
        errors = exc_info.value.errors()
        assert any("greater than 0" in str(e) for e in errors)

    def test_backoff_config_max_duration_zero_rejected(self) -> None:
        """BackoffConfig(max_duration_sec=0) → ValidationError (gt=0)."""
        with pytest.raises(ValidationError) as exc_info:
            BackoffConfig(max_duration_sec=0)
        errors = exc_info.value.errors()
        assert any("greater than 0" in str(e) for e in errors)

    def test_backoff_config_factor_below_one_rejected(self) -> None:
        """BackoffConfig(factor=0.5) → ValidationError (ge=1.0)."""
        with pytest.raises(ValidationError) as exc_info:
            BackoffConfig(factor=0.5)
        errors = exc_info.value.errors()
        assert any("greater than or equal to 1" in str(e) for e in errors)

    def test_backoff_config_factor_exactly_one_valid(self) -> None:
        """BackoffConfig(factor=1.0) → passes (ge=1.0 allows exactly 1.0)."""
        cfg = BackoffConfig(factor=1.0)
        assert cfg.factor == 1.0


# ---------------------------------------------------------------------------
# BackoffConfig — cross-field validator (check_bounds)
# ---------------------------------------------------------------------------


class TestBackoffCrossFieldConstraints:
    """Validate base_duration_sec <= max_duration_sec (check_bounds model_validator)."""

    def test_backoff_config_base_exceeds_max_rejected(self) -> None:
        """BackoffConfig(base_duration_sec=100, max_duration_sec=30) →
        ValidationError wrapping ValueError from check_bounds."""
        with pytest.raises(ValidationError) as exc_info:
            BackoffConfig(base_duration_sec=100, max_duration_sec=30)
        # The model_validator raises ValueError, which Pydantic wraps in ValidationError.
        error_msg = str(exc_info.value)
        assert "base_duration_sec" in error_msg
        assert "max_duration_sec" in error_msg

    def test_backoff_config_base_equals_max_valid(self) -> None:
        """BackoffConfig(base_duration_sec=30, max_duration_sec=30) → passes."""
        cfg = BackoffConfig(base_duration_sec=30, max_duration_sec=30)
        assert cfg.base_duration_sec == 30
        assert cfg.max_duration_sec == 30

    def test_backoff_config_defaults_valid(self) -> None:
        """BackoffConfig() → all defaults pass constraints and cross-field check."""
        cfg = BackoffConfig()
        assert cfg.base_duration_sec == 30  # gt=0 satisfied
        assert cfg.max_duration_sec == 1800  # gt=0 satisfied
        assert cfg.factor == 2.0  # ge=1.0 satisfied
        # Cross-field: 30 <= 1800 ✓
