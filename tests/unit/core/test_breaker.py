#!/usr/bin/env python3

"""Unit tests for KeyCircuitBreaker — state machine, sliding window,
opening condition, cooldown, recovery, and observability counters.

Covers the 10 breaker-core-unit scenarios from the test plan:
  - Per-worker state isolation
  - Worker restart reset
  - Sliding-window eviction
  - Fatal/client errors excluded from wave evidence
  - Threshold-based opening
  - Below-min_samples guard
  - Successful-probe recovery
  - Exponential cooldown on probe failure
  - Cooldown clamping at max
  - State-transition counter semantics
"""

from src.core.breaker import KeyCircuitBreaker
from src.core.constants import BreakerState, ErrorReason
from src.core.models import CircuitBreakerParams

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_params(**overrides) -> CircuitBreakerParams:
    """Return CircuitBreakerParams with canonical defaults, overridden by kwargs.

    Defaults match the values in
    ``config/example_full_config.yaml → gateway_policy.circuit_breaker``.
    """
    defaults: dict = {
        "window_size": 20,
        "error_rate_threshold": 0.5,
        "min_samples": 5,
        "open_duration_sec": 30.0,
        "backoff_factor": 2.0,
        "max_open_duration_sec": 300.0,
        "probe_successes_to_close": 3,
    }
    defaults.update(overrides)
    return CircuitBreakerParams(**defaults)


# ---------------------------------------------------------------------------
# 1. test_breaker_state_is_per_worker
# ---------------------------------------------------------------------------


def test_breaker_state_is_per_worker() -> None:
    """Two independent KeyCircuitBreaker instances; opening one leaves the other
    CLOSED with unaffected window and counters."""
    params = _make_params(min_samples=3)

    breaker_a = KeyCircuitBreaker(params)
    breaker_b = KeyCircuitBreaker(params)

    # Open breaker_a: 2 retryable errors + 1 success → 2/3 ≈ 0.67 ≥ 0.5
    breaker_a.record_result(False, ErrorReason.TIMEOUT)
    breaker_a.record_result(False, ErrorReason.SERVER_ERROR)
    breaker_a.record_result(True)

    assert breaker_a.state == BreakerState.OPEN
    assert breaker_b.state == BreakerState.CLOSED
    assert len(breaker_b.window) == 0
    assert breaker_b.opened_events == 0
    assert breaker_b.fail_fast_events == 0


# ---------------------------------------------------------------------------
# 2. test_worker_restart_resets_breaker
# ---------------------------------------------------------------------------


def test_worker_restart_resets_breaker() -> None:
    """A freshly constructed breaker is CLOSED with empty window and zeroed
    counters."""
    params = _make_params()
    breaker = KeyCircuitBreaker(params)

    assert breaker.state == BreakerState.CLOSED
    assert len(breaker.window) == 0
    assert breaker.opened_events == 0
    assert breaker.closed_events == 0
    assert breaker.reopened_events == 0
    assert breaker.fail_fast_events == 0
    assert breaker.probe_successes == 0
    assert breaker.current_cooldown == params.open_duration_sec


# ---------------------------------------------------------------------------
# 3. test_window_evicts_oldest_outcomes
# ---------------------------------------------------------------------------


def test_window_evicts_oldest_outcomes() -> None:
    """window_size 20, record 25 outcomes → window property holds only the 20
    most recent."""
    params = _make_params(window_size=20)
    breaker = KeyCircuitBreaker(params)

    # Fill the first 5 slots with non-retryable errors (BAD_REQUEST)
    # so the opening condition is NOT triggered while the window fills.
    for _ in range(5):
        breaker.record_result(False, ErrorReason.BAD_REQUEST)

    # Record 20 more outcomes (all successes) — these should remain.
    for _ in range(20):
        breaker.record_result(True)

    window = breaker.window
    assert len(window) == 20
    # All 20 remaining entries should be None (successes)
    assert all(reason is None for reason in window)


# ---------------------------------------------------------------------------
# 4. test_fatal_and_client_errors_not_wave_evidence
# ---------------------------------------------------------------------------


def test_fatal_and_client_errors_not_wave_evidence() -> None:
    """Failures with INVALID_KEY / BAD_REQUEST occupy window slots but do not
    count toward the retryable-error share; breaker stays CLOSED."""
    params = _make_params(min_samples=5)
    breaker = KeyCircuitBreaker(params)

    breaker.record_result(False, ErrorReason.INVALID_KEY)
    breaker.record_result(False, ErrorReason.NO_ACCESS)
    breaker.record_result(False, ErrorReason.NO_QUOTA)
    breaker.record_result(False, ErrorReason.NO_MODEL)
    breaker.record_result(False, ErrorReason.BAD_REQUEST)

    # 5 samples ≥ min_samples, but 0 retryable → error rate 0.0 < 0.5
    assert breaker.state == BreakerState.CLOSED
    assert len(breaker.window) == 5


# ---------------------------------------------------------------------------
# 5. test_threshold_reached_opens_breaker
# ---------------------------------------------------------------------------


def test_threshold_reached_opens_breaker() -> None:
    """window_size=20, min_samples=5, error_rate_threshold=0.5;
    last 6 outcomes = 3 retryable errors + 3 successes → OPEN."""
    params = _make_params(window_size=20, min_samples=5, error_rate_threshold=0.5)
    breaker = KeyCircuitBreaker(params)

    # 3 retryable errors
    breaker.record_result(False, ErrorReason.TIMEOUT)
    breaker.record_result(False, ErrorReason.SERVER_ERROR)
    breaker.record_result(False, ErrorReason.RATE_LIMITED)
    # 3 successes
    breaker.record_result(True)
    breaker.record_result(True)
    breaker.record_result(True)

    # 3 retryable / 6 total = 0.5 ≥ 0.5 → OPEN
    assert breaker.state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# 6. test_below_min_samples_stays_closed
# ---------------------------------------------------------------------------


def test_below_min_samples_stays_closed() -> None:
    """min_samples=5, only 4 outcomes (all retryable) → CLOSED."""
    params = _make_params(min_samples=5)
    breaker = KeyCircuitBreaker(params)

    for _ in range(4):
        breaker.record_result(False, ErrorReason.TIMEOUT)

    assert breaker.state == BreakerState.CLOSED


# ---------------------------------------------------------------------------
# 7. test_successful_probes_close_breaker
# ---------------------------------------------------------------------------


def test_successful_probes_close_breaker() -> None:
    """Force OPEN, advance fake clock past cooldown, begin_probe() →
    HALF_OPEN, then probe_successes_to_close consecutive successes →
    CLOSED, window cleared, cooldown reset to base."""
    params = _make_params(
        min_samples=3,
        open_duration_sec=30.0,
        probe_successes_to_close=3,
    )
    _now = [0.0]
    breaker = KeyCircuitBreaker(params, clock=lambda: _now[0])

    # Open the breaker: 2 retryable errors + 1 success → 2/3 ≈ 0.67 ≥ 0.5
    breaker.record_result(False, ErrorReason.TIMEOUT)
    breaker.record_result(False, ErrorReason.SERVER_ERROR)
    breaker.record_result(True)
    assert breaker.state == BreakerState.OPEN

    # Advance clock past cooldown and begin probing
    _now[0] = 100.0
    assert breaker.begin_probe() is True
    assert breaker.state == BreakerState.HALF_OPEN

    # Record probe_successes_to_close consecutive successes
    breaker.record_probe_success()
    breaker.record_probe_success()
    breaker.record_probe_success()

    assert breaker.state == BreakerState.CLOSED
    assert len(breaker.window) == 0
    assert breaker.current_cooldown == params.open_duration_sec
    assert breaker.closed_events == 1


# ---------------------------------------------------------------------------
# 8. test_failed_probe_reopens_with_exponential_cooldown
# ---------------------------------------------------------------------------


def test_failed_probe_reopens_with_exponential_cooldown() -> None:
    """HALF_OPEN, record_probe_failure(TIMEOUT) with current_cooldown=30 and
    backoff_factor=2.0 → OPEN, current_cooldown == 60."""
    params = _make_params(
        min_samples=3,
        open_duration_sec=30.0,
        backoff_factor=2.0,
    )
    _now = [0.0]
    breaker = KeyCircuitBreaker(params, clock=lambda: _now[0])

    # Open the breaker
    breaker.record_result(False, ErrorReason.TIMEOUT)
    breaker.record_result(False, ErrorReason.SERVER_ERROR)
    breaker.record_result(True)
    assert breaker.state == BreakerState.OPEN
    assert breaker.current_cooldown == 30.0

    # Advance clock past cooldown → HALF_OPEN
    _now[0] = 100.0
    breaker.begin_probe()
    assert breaker.state == BreakerState.HALF_OPEN

    # Fail the probe with a retryable error → re-open with doubled cooldown
    breaker.record_probe_failure(ErrorReason.TIMEOUT)

    assert breaker.state == BreakerState.OPEN
    assert breaker.current_cooldown == 60.0
    assert breaker.reopened_events == 1


# ---------------------------------------------------------------------------
# 9. test_cooldown_capped_at_maximum
# ---------------------------------------------------------------------------


def test_cooldown_capped_at_maximum() -> None:
    """Repeated re-openings clamp cooldown at max_open_duration_sec."""
    params = _make_params(
        min_samples=3,
        open_duration_sec=30.0,
        backoff_factor=2.0,
        max_open_duration_sec=300.0,
    )
    _now = [0.0]
    breaker = KeyCircuitBreaker(params, clock=lambda: _now[0])

    # Open the breaker initially
    breaker.record_result(False, ErrorReason.TIMEOUT)
    breaker.record_result(False, ErrorReason.SERVER_ERROR)
    breaker.record_result(True)
    assert breaker.state == BreakerState.OPEN
    assert breaker.current_cooldown == 30.0

    # Cycle: advance clock → begin_probe → record_probe_failure
    # Iteration 1: 30.0 * 2.0 = 60.0
    _now[0] = 100.0
    breaker.begin_probe()
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.current_cooldown == 60.0

    # Iteration 2: 60.0 * 2.0 = 120.0
    _now[0] = 200.0
    breaker.begin_probe()
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.current_cooldown == 120.0

    # Iteration 3: 120.0 * 2.0 = 240.0
    _now[0] = 400.0
    breaker.begin_probe()
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.current_cooldown == 240.0

    # Iteration 4: min(240.0 * 2.0, 300.0) = 300.0 (capped)
    _now[0] = 700.0
    breaker.begin_probe()
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.current_cooldown == 300.0

    # Iteration 5: min(300.0 * 2.0, 300.0) = 300.0 (still capped)
    _now[0] = 1100.0
    breaker.begin_probe()
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.current_cooldown == 300.0


# ---------------------------------------------------------------------------
# 10. test_state_transition_increments_counter
# ---------------------------------------------------------------------------


def test_state_transition_increments_counter() -> None:
    """CLOSED→OPEN increments opened_events by 1; also verify closed_events,
    reopened_events, fail_fast_events semantics."""
    params = _make_params(
        min_samples=3,
        open_duration_sec=30.0,
        probe_successes_to_close=3,
    )
    _now = [0.0]
    breaker = KeyCircuitBreaker(params, clock=lambda: _now[0])

    # ---- Open the breaker ----
    breaker.record_result(False, ErrorReason.TIMEOUT)
    breaker.record_result(False, ErrorReason.SERVER_ERROR)
    breaker.record_result(True)
    assert breaker.opened_events == 1
    assert breaker.state == BreakerState.OPEN

    # ---- Verify fail_fast in OPEN ----
    assert breaker.should_fail_fast() is True
    assert breaker.fail_fast_events == 1
    assert breaker.should_fail_fast() is True
    assert breaker.fail_fast_events == 2

    # ---- Transition to HALF_OPEN ----
    _now[0] = 100.0
    assert breaker.begin_probe() is True
    assert breaker.state == BreakerState.HALF_OPEN

    # ---- Reopen via probe failure ----
    breaker.record_probe_failure(ErrorReason.TIMEOUT)
    assert breaker.reopened_events == 1
    assert breaker.state == BreakerState.OPEN

    # ---- Close via successful probes ----
    _now[0] = 200.0
    breaker.begin_probe()
    breaker.record_probe_success()
    breaker.record_probe_success()
    breaker.record_probe_success()
    assert breaker.closed_events == 1
    assert breaker.state == BreakerState.CLOSED
