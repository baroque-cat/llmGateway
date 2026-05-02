#!/usr/bin/env python3

"""Tests for AdaptiveBatchController.report_batch_result() algorithm —
rate-limit backoff, transient backoff, ramp-up, and edge cases."""

import pytest

from src.core.batching.adaptive import AdaptiveBatchController
from src.core.constants import ErrorReason
from src.core.models import AdaptiveBatchingParams, CheckResult

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_controller(**kwargs):
    """Create an AdaptiveBatchController with sensible defaults, allowing overrides."""
    defaults = {
        "start_batch_size": 10,
        "max_batch_size": 50,
        "min_batch_size": 2,
        "batch_size_step": 2,
        "start_batch_delay_sec": 0.1,
        "min_batch_delay_sec": 0.01,
        "max_batch_delay_sec": 5.0,
        "delay_step_sec": 0.1,
        "rate_limit_divisor": 2,
        "rate_limit_delay_multiplier": 2.0,
        "recovery_threshold": 3,
        "recovery_step_multiplier": 2.0,
        "failure_rate_threshold": 0.3,
    }
    defaults.update(kwargs)
    return AdaptiveBatchController(params=AdaptiveBatchingParams(**defaults))


def _success(n: int) -> list[CheckResult]:
    """Create n successful CheckResult objects."""
    return [CheckResult.success() for _ in range(n)]


def _rate_limited(n: int) -> list[CheckResult]:
    """Create n rate-limited CheckResult objects."""
    return [CheckResult.fail(ErrorReason.RATE_LIMITED) for _ in range(n)]


def _transient(n: int) -> list[CheckResult]:
    """Create n transient (retryable, non-rate-limited) CheckResult objects."""
    return [CheckResult.fail(ErrorReason.TIMEOUT) for _ in range(n)]


def _fatal(n: int) -> list[CheckResult]:
    """Create n fatal CheckResult objects."""
    return [CheckResult.fail(ErrorReason.INVALID_KEY) for _ in range(n)]


# ---------------------------------------------------------------------------
# Strategy 1: Rate-limit backoff
# ---------------------------------------------------------------------------


def test_rate_limit_halves_batch_size() -> None:
    """One rate_limited result → batch_size is divided by rate_limit_divisor (2)."""
    ctrl = _make_controller(start_batch_size=10, rate_limit_divisor=2)
    ctrl.report_batch_result(_rate_limited(1) + _success(9))
    # 10 // 2 = 5
    assert ctrl.batch_size == 5


def test_rate_limit_doubles_delay() -> None:
    """One rate_limited result → batch_delay is multiplied by rate_limit_delay_multiplier (2.0)."""
    ctrl = _make_controller(start_batch_delay_sec=0.1, rate_limit_delay_multiplier=2.0)
    ctrl.report_batch_result(_rate_limited(1) + _success(9))
    # 0.1 * 2.0 = 0.2
    assert ctrl.batch_delay == 0.2


def test_rate_limit_resets_consecutive_successes() -> None:
    """Rate-limited result resets consecutive_successes to 0."""
    ctrl = _make_controller()
    ctrl._consecutive_successes = 5
    ctrl.report_batch_result(_rate_limited(1) + _success(9))
    assert ctrl.consecutive_successes == 0


def test_rate_limit_increments_event_counter() -> None:
    """Rate-limited result increments rate_limit_events counter."""
    ctrl = _make_controller()
    assert ctrl.rate_limit_events == 0
    ctrl.report_batch_result(_rate_limited(1) + _success(9))
    assert ctrl.rate_limit_events == 1


# ---------------------------------------------------------------------------
# Strategy 2: Transient backoff
# ---------------------------------------------------------------------------


def test_transient_above_threshold_triggers_backoff() -> None:
    """Transient proportion > failure_rate_threshold triggers moderate backoff."""
    ctrl = _make_controller(
        start_batch_size=10, start_batch_delay_sec=0.1, failure_rate_threshold=0.3
    )
    # 4 transient out of 10 total = 40% > 30%
    ctrl.report_batch_result(_transient(4) + _success(6))
    # batch_size -= batch_size_step = 10 - 2 = 8
    assert ctrl.batch_size == 8
    # batch_delay += delay_step_sec = 0.1 + 0.1 = 0.2
    assert ctrl.batch_delay == pytest.approx(0.2)


def test_transient_at_threshold_no_backoff() -> None:
    """Transient proportion == threshold → no backoff, ramp-up applies instead."""
    ctrl = _make_controller(
        start_batch_size=10, start_batch_delay_sec=0.1, failure_rate_threshold=0.3
    )
    # 3 transient out of 10 total = 30% == threshold (NOT > threshold)
    ctrl.report_batch_result(_transient(3) + _success(7))
    # Ramp-up: batch_size += step = 10 + 2 = 12
    assert ctrl.batch_size == 12
    # Ramp-up: batch_delay -= step = 0.1 - 0.1 = 0.0 → clamped to min 0.01
    assert ctrl.batch_delay == pytest.approx(0.01)


def test_transient_below_threshold_no_backoff() -> None:
    """Transient proportion < threshold → no backoff, ramp-up applies."""
    ctrl = _make_controller(
        start_batch_size=10, start_batch_delay_sec=0.1, failure_rate_threshold=0.3
    )
    # 2 transient out of 10 = 20% < 30%
    ctrl.report_batch_result(_transient(2) + _success(8))
    # Ramp-up: batch_size += step = 10 + 2 = 12
    assert ctrl.batch_size == 12
    # Ramp-up: batch_delay -= step = 0.1 - 0.1 = 0.0 → clamped to min 0.01
    assert ctrl.batch_delay == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# Strategy 3: Ramp-up
# ---------------------------------------------------------------------------


def test_no_errors_ramps_up() -> None:
    """All success results → batch_size increases, delay decreases."""
    ctrl = _make_controller(start_batch_size=10, start_batch_delay_sec=0.5)
    ctrl.report_batch_result(_success(10))
    # batch_size += step = 10 + 2 = 12
    assert ctrl.batch_size == 12
    # batch_delay -= step = 0.5 - 0.1 = 0.4
    assert ctrl.batch_delay == pytest.approx(0.4)


def test_ramp_up_capped_at_max_batch_size() -> None:
    """Ramp-up does not exceed max_batch_size."""
    ctrl = _make_controller(start_batch_size=49, max_batch_size=50, batch_size_step=2)
    ctrl.report_batch_result(_success(10))
    # 49 + 2 = 51 → capped at 50
    assert ctrl.batch_size == 50


def test_ramp_up_respects_min_delay() -> None:
    """Delay does not fall below min_batch_delay_sec during ramp-up."""
    ctrl = _make_controller(
        start_batch_delay_sec=0.02, min_batch_delay_sec=0.01, delay_step_sec=0.1
    )
    ctrl.report_batch_result(_success(10))
    # 0.02 - 0.1 = -0.08 → clamped to 0.01
    assert ctrl.batch_delay == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_batch_noop() -> None:
    """Empty results list → no change to batch_size, delay, or counters."""
    ctrl = _make_controller(start_batch_size=10, start_batch_delay_sec=0.1)
    initial_size = ctrl.batch_size
    initial_delay = ctrl.batch_delay
    initial_consecutive = ctrl.consecutive_successes
    initial_rl_events = ctrl.rate_limit_events

    ctrl.report_batch_result([])

    assert ctrl.batch_size == initial_size
    assert ctrl.batch_delay == initial_delay
    assert ctrl.consecutive_successes == initial_consecutive
    assert ctrl.rate_limit_events == initial_rl_events


def test_all_fatal_no_change() -> None:
    """All INVALID_KEY (fatal) results → algorithm treats as ramp-up (no special fatal handling).

    NOTE: The current algorithm classifies all-fatal batches as ramp-up because
    non_fatal_total=0 → transient_rate=0 → falls through to Priority 3 (success ramp-up).
    This test verifies the actual behavior: batch_size increases, delay decreases.
    """
    ctrl = _make_controller(start_batch_size=10, start_batch_delay_sec=0.5)
    ctrl.report_batch_result(_fatal(5))
    # All fatal → non_fatal_total=0 → transient_rate=0 → ramp-up
    # batch_size += step = 10 + 2 = 12
    assert ctrl.batch_size == 12
    # batch_delay -= step = 0.5 - 0.1 = 0.4
    assert ctrl.batch_delay == pytest.approx(0.4)


def test_rate_limited_priority_over_fatal() -> None:
    """When both rate_limited and fatal results exist, rate-limit backoff applies."""
    ctrl = _make_controller(start_batch_size=10, start_batch_delay_sec=0.1)
    # 2 fatal + 1 rate_limited + 7 success
    ctrl.report_batch_result(_fatal(2) + _rate_limited(1) + _success(7))
    # Rate-limited backoff: batch_size // divisor = 10 // 2 = 5
    assert ctrl.batch_size == 5
    # Rate-limited backoff: delay * multiplier = 0.1 * 2.0 = 0.2
    assert ctrl.batch_delay == pytest.approx(0.2)
    assert ctrl.consecutive_successes == 0
