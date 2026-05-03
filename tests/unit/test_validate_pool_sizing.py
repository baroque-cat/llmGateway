#!/usr/bin/env python3

"""
Unit tests for pool sizing validation via Config model_validator in schemas.py.

The old validate_pool_sizing() function in main.py is gone.
Validation is now a model_validator on Config that:
  - raises ValueError if worst_case > 97 (blocks startup)
  - logs WARNING if worst_case > 77 (80% threshold)

Test IDs:
  UT-VP01 – workers=8, max_size=15 → ValueError (worst_case = 135 > 97)
  UT-VP02 – workers=4, max_size=15 → passes (worst_case = 75 ≤ 97, ≤ 77 → no warning)
  UT-VP03 – workers=4, max_size=19 → passes (worst_case = 95 < 97, > 77 → WARNING)
  UT-VP04 – workers=4, max_size=20 → ValueError (worst_case = 100 > 97)
  UT-VP05 – workers=5, max_size=15 → WARNING logged (worst_case = 90, ~92%)
  UT-VP06 – workers=2, max_size=10 → no warning (worst_case = 30, ~30%)
  UT-VP07 – Error message contains actionable values
  UT-VP08 – processes = gateway.workers + 1 (Keeper accounted for)
"""

import logging

import pytest
from pydantic import ValidationError

from src.config.schemas import Config, DatabaseConfig, DatabasePoolConfig, GatewayConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOGGER_NAME = "src.config.schemas"


def _make_config(workers: int, max_size: int) -> Config:
    """Build a Config with the given gateway workers and pool max_size.

    All other fields use their defaults.
    """
    return Config(
        gateway=GatewayConfig(workers=workers),
        database=DatabaseConfig(pool=DatabasePoolConfig(max_size=max_size)),
    )


def _try_config(workers: int, max_size: int) -> ValidationError | None:
    """Attempt to create a Config; return ValidationError if raised, else None."""
    try:
        _make_config(workers, max_size)
        return None
    except ValidationError as exc:
        return exc


# ---------------------------------------------------------------------------
# UT-VP01 / UT-VP04: Overflow → ValueError (blocks startup)
# ---------------------------------------------------------------------------


class TestPoolSizingOverflow:
    """Cases where worst_case > 97 → ValueError raised."""

    def test_ut_vp01_workers8_max15_raises_valueerror(self) -> None:
        """UT-VP01: workers=8, max_size=15 → (8+1)*15=135 > 97 → ValueError."""
        with pytest.raises(ValueError):
            _make_config(workers=8, max_size=15)

    def test_ut_vp04_workers4_max20_raises_valueerror(self) -> None:
        """UT-VP04: workers=4, max_size=20 → (4+1)*20=100 > 97 → ValueError."""
        with pytest.raises(ValueError):
            _make_config(workers=4, max_size=20)


# ---------------------------------------------------------------------------
# UT-VP02 / UT-VP03: Valid configs → no ValueError
# ---------------------------------------------------------------------------


class TestPoolSizingPasses:
    """Cases where worst_case ≤ 97 → Config created successfully."""

    def test_ut_vp02_workers4_max15_passes(self) -> None:
        """UT-VP02: workers=4, max_size=15 → (4+1)*15=75 ≤ 97 → passes."""
        config = _make_config(workers=4, max_size=15)
        assert config.gateway.workers == 4
        assert config.database.pool.max_size == 15

    def test_ut_vp03_workers4_max19_passes(self) -> None:
        """UT-VP03: workers=4, max_size=19 → (4+1)*19=95 < 97 → passes."""
        config = _make_config(workers=4, max_size=19)
        assert config.gateway.workers == 4
        assert config.database.pool.max_size == 19


# ---------------------------------------------------------------------------
# UT-VP05 / UT-VP06: WARNING threshold (80% of 97 = 77)
# ---------------------------------------------------------------------------


class TestPoolSizingWarning:
    """Cases testing WARNING log emission at the 80% threshold."""

    def test_ut_vp05_workers5_max15_warning_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-VP05: workers=5, max_size=15 → (5+1)*15=90 > 77 → WARNING logged."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            _make_config(workers=5, max_size=15)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        # Verify key content: 6 processes, worst_case=90
        assert "6 processes" in msg
        assert "pool.max_size=15" in msg
        assert "90" in msg

    def test_ut_vp06_workers2_max10_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """UT-VP06: workers=2, max_size=10 → (2+1)*10=30 ≤ 77 → no warning."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            _make_config(workers=2, max_size=10)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# UT-VP07: Error message contains actionable values
# ---------------------------------------------------------------------------


class TestPoolSizingErrorMessage:
    """Verify the ValueError message contains actionable guidance."""

    def test_ut_vp07_error_message_contains_actionable_values(self) -> None:
        """UT-VP07: ValueError message contains 'processes', 'pool.max_size',
        'connections', '97', 'Reduce'.
        """
        exc = _try_config(workers=8, max_size=15)
        assert exc is not None, "Expected ValidationError but Config was created"
        msg = str(exc)
        assert "processes" in msg
        assert "pool.max_size" in msg
        assert "connections" in msg
        assert "97" in msg
        assert "Reduce" in msg


# ---------------------------------------------------------------------------
# UT-VP08: processes = gateway.workers + 1 (Keeper accounted for)
# ---------------------------------------------------------------------------


class TestPoolSizingKeeperAccounted:
    """Verify that the +1 for Keeper is included in the process count."""

    def test_ut_vp08_processes_includes_keeper(self) -> None:
        """UT-VP08: Error message shows processes = workers + 1 (Keeper accounted for).

        With workers=8: processes = 8 + 1 = 9.
        The error message should contain '9 processes' and '8 gateway + 1 keeper'.
        """
        exc = _try_config(workers=8, max_size=15)
        assert exc is not None, "Expected ValidationError but Config was created"
        msg = str(exc)
        # 8 gateway workers + 1 keeper = 9 processes
        assert "9 processes" in msg
        # Breakdown showing the Keeper contribution
        assert "8 gateway" in msg
        assert "1 keeper" in msg