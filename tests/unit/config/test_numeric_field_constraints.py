#!/usr/bin/env python3

"""
Tests for numeric field constraints on RetryOnErrorConfig and DatabaseConfig —
attempts (ge=0), backoff_sec (ge=0), backoff_factor (ge=1.0), port (gt=0, lt=65536).

Covers the 11 scenarios defined in the harden-config-validation test plan (G7).
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import DatabaseConfig, RetryOnErrorConfig

# ---------------------------------------------------------------------------
# RetryOnErrorConfig — attempts (ge=0)
# ---------------------------------------------------------------------------


class TestRetryOnErrorAttempts:
    """Validate attempts field constraint: ge=0 (0 is valid, negative rejected)."""

    def test_retry_on_error_attempts_negative_rejected(self) -> None:
        """RetryOnErrorConfig(attempts=-1) → ValidationError (ge=0)."""
        with pytest.raises(ValidationError):
            RetryOnErrorConfig(attempts=-1)

    def test_retry_on_error_attempts_zero_valid(self) -> None:
        """RetryOnErrorConfig(attempts=0) → passes (ge=0 allows zero)."""
        cfg = RetryOnErrorConfig(attempts=0)
        assert cfg.attempts == 0


# ---------------------------------------------------------------------------
# RetryOnErrorConfig — backoff_sec (ge=0)
# ---------------------------------------------------------------------------


class TestRetryOnErrorBackoffSec:
    """Validate backoff_sec field constraint: ge=0 (0 is valid, negative rejected)."""

    def test_retry_on_error_backoff_sec_negative_rejected(self) -> None:
        """RetryOnErrorConfig(backoff_sec=-0.5) → ValidationError (ge=0)."""
        with pytest.raises(ValidationError):
            RetryOnErrorConfig(backoff_sec=-0.5)

    def test_retry_on_error_backoff_sec_zero_valid(self) -> None:
        """RetryOnErrorConfig(backoff_sec=0) → passes (ge=0 allows zero)."""
        cfg = RetryOnErrorConfig(backoff_sec=0)
        assert cfg.backoff_sec == 0


# ---------------------------------------------------------------------------
# RetryOnErrorConfig — backoff_factor (ge=1.0)
# ---------------------------------------------------------------------------


class TestRetryOnErrorBackoffFactor:
    """Validate backoff_factor field constraint: ge=1.0 (1.0 valid, <1.0 rejected)."""

    def test_retry_on_error_backoff_factor_below_one_rejected(self) -> None:
        """RetryOnErrorConfig(backoff_factor=0.5) → ValidationError (ge=1.0)."""
        with pytest.raises(ValidationError):
            RetryOnErrorConfig(backoff_factor=0.5)

    def test_retry_on_error_backoff_factor_exactly_one_valid(self) -> None:
        """RetryOnErrorConfig(backoff_factor=1.0) → passes (ge=1.0 allows exactly 1.0)."""
        cfg = RetryOnErrorConfig(backoff_factor=1.0)
        assert cfg.backoff_factor == 1.0


# ---------------------------------------------------------------------------
# DatabaseConfig — port (gt=0, lt=65536)
# ---------------------------------------------------------------------------


class TestDatabaseConfigPort:
    """Validate port field constraint: gt=0 and lt=65536."""

    def test_database_config_port_above_65535_rejected(self) -> None:
        """DatabaseConfig(port=70000) → ValidationError (lt=65536)."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=70000)

    def test_database_config_port_65535_valid(self) -> None:
        """DatabaseConfig(port=65535) → passes (boundary: lt=65536 allows 65535)."""
        cfg = DatabaseConfig(port=65535)
        assert cfg.port == 65535

    def test_database_config_port_65536_rejected(self) -> None:
        """DatabaseConfig(port=65536) → ValidationError (lt=65536 rejects 65536)."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=65536)

    def test_database_config_port_zero_rejected(self) -> None:
        """DatabaseConfig(port=0) → ValidationError (gt=0 rejects zero)."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=0)

    def test_database_config_port_5432_valid(self) -> None:
        """DatabaseConfig(port=5432) → passes (standard PostgreSQL port)."""
        cfg = DatabaseConfig(port=5432)
        assert cfg.port == 5432
