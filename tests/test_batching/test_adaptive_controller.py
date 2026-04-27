#!/usr/bin/env python3

"""
Test suite for AdaptiveBatchController (UC-01..UC-32).

These tests verify the adaptive batch controller's:
- Initialization and boundary enforcement
- Ramp-up behavior on success (moderate and aggressive)
- Aggressive backoff on rate-limited results
- Moderate backoff on transient errors exceeding threshold
- Fatal error handling (ignored for batch sizing)
- Priority ordering of backoff strategies
- Edge cases (empty batch, boundary values)
"""


from src.config.schemas import AdaptiveBatchingConfig
from src.core.batching import AdaptiveBatchController
from src.core.constants import ErrorReason
from src.core.models import CheckResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _success_results(n: int) -> list[CheckResult]:
    """Create n successful CheckResult objects."""
    return [CheckResult.success() for _ in range(n)]


def _rate_limited_results(n: int) -> list[CheckResult]:
    """Create n rate-limited CheckResult objects."""
    return [CheckResult.fail(reason=ErrorReason.RATE_LIMITED) for _ in range(n)]


def _transient_results(n: int) -> list[CheckResult]:
    """Create n transient (retryable, non-rate-limited) CheckResult objects."""
    return [CheckResult.fail(reason=ErrorReason.TIMEOUT) for _ in range(n)]


def _fatal_results(n: int) -> list[CheckResult]:
    """Create n fatal CheckResult objects."""
    return [CheckResult.fail(reason=ErrorReason.INVALID_KEY) for _ in range(n)]


def _make_controller(
    initial_batch_size: int = 30,
    initial_batch_delay: float = 15.0,
    **config_kwargs: object,
) -> AdaptiveBatchController:
    """Create a controller with the given initial values and config overrides."""
    config = AdaptiveBatchingConfig(**config_kwargs)
    return AdaptiveBatchController(
        config=config,
        initial_batch_size=initial_batch_size,
        initial_batch_delay=initial_batch_delay,
    )


# ===========================================================================
# UC-01..UC-04: Initialization and boundary enforcement
# ===========================================================================


def test_uc01_initialization_with_default_values() -> None:
    """
    Create AdaptiveBatchController with default config, initial_batch_size=30,
    initial_batch_delay=15.0. Verify batch_size == 30, batch_delay == 15.0,
    consecutive_successes == 0.
    """
    controller = _make_controller(initial_batch_size=30, initial_batch_delay=15.0)

    assert controller.batch_size == 30
    assert controller.batch_delay == 15.0
    assert controller.consecutive_successes == 0


def test_uc02_initialization_with_user_bounds() -> None:
    """
    Create controller with min_batch_size=5, max_batch_size=50,
    min_batch_delay=3.0, max_batch_delay=60.0. Verify bounds stored and
    batch_size/batch_delay equal initial values.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
        min_batch_size=5,
        max_batch_size=50,
        min_batch_delay_sec=3.0,
        max_batch_delay_sec=60.0,
    )

    assert controller.batch_size == 30
    assert controller.batch_delay == 15.0
    assert controller.consecutive_successes == 0

    # Verify bounds are stored in config
    assert controller._config.min_batch_size == 5
    assert controller._config.max_batch_size == 50
    assert controller._config.min_batch_delay_sec == 3.0
    assert controller._config.max_batch_delay_sec == 60.0


def test_uc03_initial_batch_size_exceeds_max_capped() -> None:
    """
    Pass initial_batch_size=100, max_batch_size=50.
    Verify batch_size capped at 50, not 100.
    """
    controller = _make_controller(
        initial_batch_size=100,
        initial_batch_delay=15.0,
        max_batch_size=50,
    )

    assert controller.batch_size == 50


def test_uc04_initial_batch_delay_below_min_capped() -> None:
    """
    Pass initial_batch_delay=1.0, min_batch_delay=3.0.
    Verify batch_delay capped at 3.0, not 1.0.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=1.0,
        min_batch_delay_sec=3.0,
    )

    assert controller.batch_delay == 3.0


# ===========================================================================
# UC-05..UC-11: Ramp-up on success (moderate and aggressive)
# ===========================================================================


def test_uc05_moderate_rampup_single_success() -> None:
    """
    Call report_batch_result with 10 success results.
    Verify batch_size += 5 (30→35), batch_delay -= 2.0 (15→13.0),
    consecutive_successes == 1.
    """
    controller = _make_controller(initial_batch_size=30, initial_batch_delay=15.0)
    controller.report_batch_result(_success_results(10))

    assert controller.batch_size == 35
    assert controller.batch_delay == 13.0
    assert controller.consecutive_successes == 1


def test_uc06_moderate_rampup_four_consecutive_successes() -> None:
    """
    Call report_batch_result with success 4 times consecutively.
    Verify batch_size == 30 + 4*5 = 50 (capped at max),
    batch_delay == 15 - 4*2 = 7.0, consecutive_successes == 4.
    """
    controller = _make_controller(initial_batch_size=30, initial_batch_delay=15.0)

    for _ in range(4):
        controller.report_batch_result(_success_results(10))

    assert controller.batch_size == 50  # 30 + 4*5 = 50, capped at max
    assert controller.batch_delay == 7.0  # 15 - 4*2 = 7.0
    assert controller.consecutive_successes == 4


def test_uc07_aggressive_rampup_five_consecutive_successes() -> None:
    """
    On 5th consecutive success, step multiplier doubles (recovery_step_multiplier=2.0).
    Verify batch_size += 10 (not +5), batch_delay -= 4.0 (not -2.0),
    consecutive_successes == 5.
    """
    # Use large max and small min to observe the aggressive step clearly
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
        max_batch_size=100,
        min_batch_delay_sec=1.0,
    )

    # 4 moderate successes first
    for _ in range(4):
        controller.report_batch_result(_success_results(10))

    # State after 4 successes: batch_size=50, batch_delay=7.0, consecutive=4
    assert controller.batch_size == 50
    assert controller.batch_delay == 7.0
    assert controller.consecutive_successes == 4

    # 5th success — aggressive ramp-up (step multiplier = 2.0)
    controller.report_batch_result(_success_results(10))

    # batch_size += int(5 * 2.0) = +10 → 60
    # batch_delay -= 2.0 * 2.0 = -4.0 → 3.0
    assert controller.batch_size == 60
    assert controller.batch_delay == 3.0
    assert controller.consecutive_successes == 5


def test_uc08_rampup_capped_at_max_batch_size() -> None:
    """
    Start with batch_size=45, call success, verify capped at 50.
    Another success — batch_size stays at 50 (capped).
    """
    controller = _make_controller(
        initial_batch_size=45,
        initial_batch_delay=15.0,
    )

    controller.report_batch_result(_success_results(10))
    assert controller.batch_size == 50  # min(45+5, 50) = 50

    controller.report_batch_result(_success_results(10))
    assert controller.batch_size == 50  # still capped at max


def test_uc09_rampup_capped_at_min_batch_delay() -> None:
    """
    Start with batch_delay=5.0, min_batch_delay=3.0.
    Success: batch_delay = max(5.0-2.0, 3.0) = 3.0.
    Another success: batch_delay stays 3.0 (capped).
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=5.0,
        min_batch_delay_sec=3.0,
    )

    controller.report_batch_result(_success_results(10))
    assert controller.batch_delay == 3.0  # max(5.0-2.0, 3.0) = 3.0

    controller.report_batch_result(_success_results(10))
    assert controller.batch_delay == 3.0  # still capped at min


def test_uc10_aggressive_rampup_capped_by_max_batch_size() -> None:
    """
    batch_size=48, consecutive_successes=4 (5th will trigger aggressive).
    Success → min(48+10, 50) = 50.
    """
    controller = _make_controller(
        initial_batch_size=48,
        initial_batch_delay=15.0,
        max_batch_size=50,
    )

    # Set up state directly so batch_size=48 and consecutive=4
    # (5th success will trigger aggressive ramp-up)
    controller._consecutive_successes = 4
    controller._batch_size = 48

    controller.report_batch_result(_success_results(10))

    assert controller.batch_size == 50  # min(48+10, 50) = 50


def test_uc11_aggressive_rampup_capped_by_min_batch_delay() -> None:
    """
    batch_delay=5.0, consecutive_successes=4 (5th triggers aggressive).
    Success → max(5.0-4.0, 3.0) = 3.0.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=5.0,
        min_batch_delay_sec=3.0,
    )

    # Set up state: consecutive=4, batch_delay=5.0
    controller._consecutive_successes = 4
    controller._batch_delay = 5.0

    controller.report_batch_result(_success_results(10))

    assert controller.batch_delay == 3.0  # max(5.0-4.0, 3.0) = 3.0


# ===========================================================================
# UC-12..UC-16: Aggressive backoff on RATE_LIMITED
# ===========================================================================


def test_uc12_rate_limit_backoff_batch_size_halved() -> None:
    """
    batch_size=40, report with 1 RATE_LIMITED.
    Verify batch_size == 20 (40 // 2), consecutive_successes == 0.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)

    assert controller.batch_size == 20  # 40 // 2 = 20
    assert controller.consecutive_successes == 0


def test_uc13_rate_limit_backoff_delay_doubled() -> None:
    """
    batch_delay=10.0, rate_limited=1.
    Verify batch_delay == 20.0 (10.0 * 2.0).
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=10.0,
    )

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)

    assert controller.batch_delay == 20.0  # 10.0 * 2.0 = 20.0


def test_uc14_rate_limit_backoff_delay_capped_by_max() -> None:
    """
    batch_delay=40.0, max=60.0, rate_limited → min(40*2, 60) = 60.0.
    Second rate_limited: min(60*2, 60) = 60.0 (capped).
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=40.0,
        max_batch_delay_sec=60.0,
    )

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)
    assert controller.batch_delay == 60.0  # min(40*2, 60) = 60.0

    controller.report_batch_result(results)
    assert controller.batch_delay == 60.0  # min(60*2, 60) = 60.0 (capped)


def test_uc15_rate_limit_backoff_batch_size_min_floor() -> None:
    """
    batch_size=6, min=5, rate_limited → max(6//2, 5) = max(3, 5) = 5.
    Second rate_limited: max(5//2, 5) = max(2, 5) = 5 (capped).
    """
    controller = _make_controller(
        initial_batch_size=6,
        initial_batch_delay=10.0,
        min_batch_size=5,
    )

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)
    assert controller.batch_size == 5  # max(6//2, 5) = max(3, 5) = 5

    controller.report_batch_result(results)
    assert controller.batch_size == 5  # max(5//2, 5) = max(2, 5) = 5 (capped)


def test_uc16_rate_limited_resets_consecutive_successes() -> None:
    """
    consecutive_successes=7, rate_limited → consecutive_successes == 0.
    Next success: step = +5 (not +10, because consecutive < recovery_threshold).
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
        max_batch_size=100,
    )

    # Build up consecutive successes to 7
    controller._consecutive_successes = 7

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)
    assert controller.consecutive_successes == 0
    # After rate-limited: batch_size = 30 // 2 = 15

    # Next success should use moderate step (+5), not aggressive (+10)
    controller.report_batch_result(_success_results(10))
    assert controller.batch_size == 20  # 15 + 5 = 20 (moderate step)
    assert controller.consecutive_successes == 1


# ===========================================================================
# UC-17..UC-22: Moderate backoff on transient > 30%
# ===========================================================================


def test_uc17_moderate_backoff_transient_above_threshold() -> None:
    """
    batch_size=40, batch_delay=10.0, total=10, transient=4 (40%).
    Verify batch_size -= 5 = 35, batch_delay += 2.0 = 12.0,
    consecutive_successes == 0.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _transient_results(4) + _success_results(6)  # 40% transient
    controller.report_batch_result(results)

    assert controller.batch_size == 35  # 40 - 5 = 35
    assert controller.batch_delay == 12.0  # 10.0 + 2.0 = 12.0
    assert controller.consecutive_successes == 0


def test_uc18_moderate_backoff_transient_at_boundary_no_backoff() -> None:
    """
    total=10, transient=3 (30%). This does NOT exceed 30% (strictly >),
    so no moderate backoff. Falls through to ramp-up.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    results = _transient_results(3) + _success_results(7)  # 30% transient (boundary)
    controller.report_batch_result(results)

    # Ramp-up applies (not backoff), because transient_rate == 0.3 is NOT > 0.3
    assert controller.batch_size == 35  # 30 + 5 = 35
    assert controller.batch_delay == 13.0  # 15 - 2.0 = 13.0
    assert controller.consecutive_successes == 1


def test_uc19_moderate_backoff_transient_below_threshold_rampup() -> None:
    """
    total=10, transient=2 (20%). No backoff, ramp-up applies.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    results = _transient_results(2) + _success_results(8)  # 20% transient
    controller.report_batch_result(results)

    # Ramp-up applies
    assert controller.batch_size == 35  # 30 + 5 = 35
    assert controller.batch_delay == 13.0  # 15 - 2.0 = 13.0
    assert controller.consecutive_successes == 1


def test_uc20_moderate_backoff_batch_size_min_floor() -> None:
    """
    batch_size=8, min=5, transient>30% → max(8-5, 5) = 5.
    """
    controller = _make_controller(
        initial_batch_size=8,
        initial_batch_delay=10.0,
        min_batch_size=5,
    )

    results = _transient_results(4) + _success_results(6)  # 40% transient
    controller.report_batch_result(results)

    assert controller.batch_size == 5  # max(8-5, 5) = 5


def test_uc21_moderate_backoff_delay_max_ceiling() -> None:
    """
    batch_delay=58.0, max=60.0, transient>30% → min(58+2, 60) = 60.0.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=58.0,
        max_batch_delay_sec=60.0,
    )

    results = _transient_results(4) + _success_results(6)  # 40% transient
    controller.report_batch_result(results)

    assert controller.batch_delay == 60.0  # min(58+2, 60) = 60.0


def test_uc22_moderate_backoff_resets_consecutive_successes() -> None:
    """
    consecutive_successes=4, transient>30% → consecutive_successes == 0.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    controller._consecutive_successes = 4

    results = _transient_results(4) + _success_results(6)  # 40% transient
    controller.report_batch_result(results)

    assert controller.consecutive_successes == 0


# ===========================================================================
# UC-23..UC-26: Fatal errors ignored
# ===========================================================================


def test_uc23_fatal_errors_ignored_rampup_applies() -> None:
    """
    batch_size=30, all 10 results are fatal.
    Verify ramp-up applies (batch_size=35, batch_delay=13.0).
    Fatal errors completely excluded from failure rate calculation.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    results = _fatal_results(10)
    controller.report_batch_result(results)

    # All fatal → non_fatal_total = 0 → transient_rate = 0 → ramp-up
    assert controller.batch_size == 35  # 30 + 5 = 35
    assert controller.batch_delay == 13.0  # 15 - 2.0 = 13.0
    assert controller.consecutive_successes == 1


def test_uc24_fatal_excluded_from_transient_rate() -> None:
    """
    total=10, fatal=3, transient=3. Transient rate = 3/(10-3) = 3/7 ≈ 42.8% > 30%.
    Moderate backoff applies.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _fatal_results(3) + _transient_results(3) + _success_results(4)
    controller.report_batch_result(results)

    assert controller.batch_size == 35  # 40 - 5 = 35
    assert controller.batch_delay == 12.0  # 10 + 2 = 12.0
    assert controller.consecutive_successes == 0


def test_uc25_mixed_fatal_rate_limited_rate_limited_priority() -> None:
    """
    total=10, fatal=2, transient=0, rate_limited=1.
    Rate-limited backoff (aggressive) applies, fatal ignored.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _fatal_results(2) + _rate_limited_results(1) + _success_results(7)
    controller.report_batch_result(results)

    assert controller.batch_size == 20  # 40 // 2 = 20
    assert controller.batch_delay == 20.0  # 10 * 2 = 20.0
    assert controller.consecutive_successes == 0


def test_uc26_all_fatal_treated_as_success_rampup() -> None:
    """
    total=5, fatal=5. Since 0 transient from 0 non-fatal, ramp-up.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    results = _fatal_results(5)
    controller.report_batch_result(results)

    assert controller.batch_size == 35  # 30 + 5 = 35
    assert controller.batch_delay == 13.0  # 15 - 2.0 = 13.0
    assert controller.consecutive_successes == 1


# ===========================================================================
# UC-27..UC-28: Priority ordering of backoff strategies
# ===========================================================================


def test_uc27_rate_limited_and_transient_rate_limited_wins() -> None:
    """
    total=10, fatal=0, transient=4, rate_limited=1.
    Aggressive backoff (rate_limited) wins over moderate backoff.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _rate_limited_results(1) + _transient_results(4) + _success_results(5)
    controller.report_batch_result(results)

    assert controller.batch_size == 20  # 40 // 2 = 20 (aggressive)
    assert controller.batch_delay == 20.0  # 10 * 2 = 20.0 (aggressive)
    assert controller.consecutive_successes == 0


def test_uc28_priority_order_rate_limited_then_transient_then_success() -> None:
    """
    Verify the priority order: rate_limited > transient > success ramp-up.
    Demonstrated through three independent scenarios.
    """
    # Priority 1: rate_limited triggers even when transient > 30%
    ctrl_rl = _make_controller(initial_batch_size=40, initial_batch_delay=10.0)
    ctrl_rl.report_batch_result(
        _rate_limited_results(1) + _transient_results(4) + _success_results(5)
    )
    assert ctrl_rl.batch_size == 20  # aggressive backoff, not moderate
    assert ctrl_rl.batch_delay == 20.0

    # Priority 2: transient > 30% triggers moderate backoff (no rate_limited)
    ctrl_tr = _make_controller(initial_batch_size=40, initial_batch_delay=10.0)
    ctrl_tr.report_batch_result(_transient_results(4) + _success_results(6))
    assert ctrl_tr.batch_size == 35  # moderate backoff, not ramp-up
    assert ctrl_tr.batch_delay == 12.0

    # Priority 3: success triggers ramp-up (no rate_limited, transient <= 30%)
    ctrl_su = _make_controller(initial_batch_size=30, initial_batch_delay=15.0)
    ctrl_su.report_batch_result(_success_results(10))
    assert ctrl_su.batch_size == 35  # ramp-up
    assert ctrl_su.batch_delay == 13.0


# ===========================================================================
# UC-29..UC-32: Edge cases
# ===========================================================================


def test_uc29_empty_batch_no_op() -> None:
    """
    Call report_batch_result with empty list.
    Verify state unchanged (no-op).
    """
    controller = _make_controller(initial_batch_size=30, initial_batch_delay=15.0)

    initial_size = controller.batch_size
    initial_delay = controller.batch_delay
    initial_consecutive = controller.consecutive_successes

    controller.report_batch_result([])

    assert controller.batch_size == initial_size
    assert controller.batch_delay == initial_delay
    assert controller.consecutive_successes == initial_consecutive


def test_uc30_all_transient_moderate_backoff() -> None:
    """
    total=10, transient=10, fatal=0, rate_limited=0.
    Transient rate = 100% > 30%. Moderate backoff applies.
    """
    controller = _make_controller(
        initial_batch_size=40,
        initial_batch_delay=10.0,
    )

    results = _transient_results(10)
    controller.report_batch_result(results)

    assert controller.batch_size == 35  # 40 - 5 = 35
    assert controller.batch_delay == 12.0  # 10 + 2 = 12.0
    assert controller.consecutive_successes == 0


def test_uc31_batch_size_1_rate_limited_min_floor() -> None:
    """
    batch_size=1, min_batch_size=1. Rate_limited → max(1//2, 1) = 1.
    Cannot go below min_batch_size.
    """
    controller = _make_controller(
        initial_batch_size=1,
        initial_batch_delay=10.0,
        min_batch_size=1,
        max_batch_size=50,
    )

    results = _rate_limited_results(1) + _success_results(9)
    controller.report_batch_result(results)

    assert controller.batch_size == 1  # max(1//2, 1) = max(0, 1) = 1


def test_uc32_consecutive_successes_not_reset_transient_below_threshold() -> None:
    """
    consecutive_successes=3, transient=2/10=20% → consecutive_successes=4.
    Ramp-up continues because transient <= 30%.
    """
    controller = _make_controller(
        initial_batch_size=30,
        initial_batch_delay=15.0,
    )

    controller._consecutive_successes = 3

    results = _transient_results(2) + _success_results(8)  # 20% transient
    controller.report_batch_result(results)

    assert controller.consecutive_successes == 4  # ramp-up, not reset
    assert controller.batch_size == 35  # 30 + 5 = 35
    assert controller.batch_delay == 13.0  # 15 - 2.0 = 13.0
