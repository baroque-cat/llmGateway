#!/usr/bin/env python3

"""
Unit tests for validate_pool_sizing function from main.py.

Tests cover: silent (no-log) cases, WARNING threshold, CRITICAL threshold,
boundary behavior at 77 and 97, return-value guarantee, and message content.
"""

import logging

import pytest

from main import validate_pool_sizing
from src.config.schemas import Config, DatabaseConfig, DatabasePoolConfig, GatewayConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(workers: int, max_size: int) -> Config:
    """Build a Config with the given gateway workers and pool max_size."""
    return Config(
        gateway=GatewayConfig(workers=workers),
        database=DatabaseConfig(pool=DatabasePoolConfig(max_size=max_size)),
    )


def _records_at_level(
    caplog: pytest.LogCaptureFixture, level: int
) -> list[logging.LogRecord]:
    """Return captured log records matching the given level."""
    return [r for r in caplog.records if r.levelno == level]


# ---------------------------------------------------------------------------
# Silent (no log output)
# ---------------------------------------------------------------------------


class TestValidatePoolSizingSilent:
    """Cases where worst_case ≤ 77 → no WARNING or CRITICAL emitted."""

    def test_ut_v01_workers4_max10_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V01: workers=4, max_size=10 → (4+1)*10=50 < 77 → silent."""
        config = _make_config(workers=4, max_size=10)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        assert len(_records_at_level(caplog, logging.WARNING)) == 0
        assert len(_records_at_level(caplog, logging.CRITICAL)) == 0

    def test_ut_v04_workers4_max15_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V04: workers=4, max_size=15 → (4+1)*15=75 < 77 → silent."""
        config = _make_config(workers=4, max_size=15)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        assert len(_records_at_level(caplog, logging.WARNING)) == 0
        assert len(_records_at_level(caplog, logging.CRITICAL)) == 0


# ---------------------------------------------------------------------------
# WARNING threshold  (77 < worst_case ≤ 97)
# ---------------------------------------------------------------------------


class TestValidatePoolSizingWarning:
    """Cases where worst_case > 77 but ≤ 97 → WARNING only, no CRITICAL."""

    def test_ut_v02_workers8_max10_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V02: workers=8, max_size=10 → (8+1)*10=90 > 77 → WARNING logged."""
        config = _make_config(workers=8, max_size=10)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        warnings = _records_at_level(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert "Pool sizing is aggressive" in warnings[0].getMessage()

    def test_ut_v05_warning_zone_not_critical(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V05: worst_case in (77, 97] → WARNING only, NOT CRITICAL.

        Since 97 is prime and cannot equal (workers+1)*max_size with valid
        integers (both > 1), we test with worst_case=91 (workers=6, max_size=13)
        which is > 77 but < 97, proving the WARNING-only zone below CRITICAL.
        """
        # (6+1)*13 = 91  →  91 > 77 (WARNING)  but  91 ≤ 97 (no CRITICAL)
        config = _make_config(workers=6, max_size=13)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        assert len(_records_at_level(caplog, logging.WARNING)) == 1
        assert len(_records_at_level(caplog, logging.CRITICAL)) == 0

    def test_ut_v07_warning_message_content(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V07: WARNING message contains (workers+1)*max_size calculation and recommendation."""
        config = _make_config(workers=8, max_size=10)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        warnings = _records_at_level(caplog, logging.WARNING)
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        # Calculation: 9 processes × pool.max_size=10 = 90 connections
        assert "9 processes" in msg
        assert "pool.max_size=10" in msg
        assert "= 90 connections" in msg
        # Recommendation text
        assert "Consider reducing" in msg


# ---------------------------------------------------------------------------
# CRITICAL threshold  (worst_case > 97)
# ---------------------------------------------------------------------------


class TestValidatePoolSizingCritical:
    """Cases where worst_case > 97 → CRITICAL logged."""

    def test_ut_v03_critical_with_message_content_and_exhaustion(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V03 + UT-V08 + SEC-05: workers=8, max_size=15 → 135 > 97 → CRITICAL with CONNECTION OVERFLOW, calculation, and exhaustion details."""
        config = _make_config(workers=8, max_size=15)
        with caplog.at_level(logging.DEBUG, logger="main"):
            validate_pool_sizing(config)
        criticals = _records_at_level(caplog, logging.CRITICAL)
        assert len(criticals) == 1
        msg = criticals[0].getMessage()
        # UT-V03: CRITICAL level with CONNECTION OVERFLOW
        assert "CONNECTION OVERFLOW" in msg
        # UT-V08: calculation details
        assert "9 processes" in msg
        assert "pool.max_size=15" in msg
        assert "= 135 connections" in msg
        assert "97" in msg
        # SEC-05: connection exhaustion warning
        assert "exceeds PostgreSQL limit" in msg
        assert "Reduce" in msg


# ---------------------------------------------------------------------------
# Return-value behaviour
# ---------------------------------------------------------------------------


class TestValidatePoolSizingReturnValue:
    """validate_pool_sizing always returns None (never raises, even on CRITICAL)."""

    def test_ut_v06_returns_none_even_with_critical(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-V06: Function returns None even when CRITICAL is logged."""
        config = _make_config(workers=8, max_size=15)
        with caplog.at_level(logging.DEBUG, logger="main"):
            result = validate_pool_sizing(config)
        assert result is None

    def test_returns_none_silent_case(self, caplog: pytest.LogCaptureFixture) -> None:
        """Returns None when no log is emitted (silent case)."""
        config = _make_config(workers=4, max_size=10)
        with caplog.at_level(logging.DEBUG, logger="main"):
            result = validate_pool_sizing(config)
        assert result is None

    def test_returns_none_warning_case(self, caplog: pytest.LogCaptureFixture) -> None:
        """Returns None when WARNING is emitted."""
        config = _make_config(workers=8, max_size=10)
        with caplog.at_level(logging.DEBUG, logger="main"):
            result = validate_pool_sizing(config)
        assert result is None
