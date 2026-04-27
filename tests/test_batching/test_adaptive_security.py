"""
Security tests for AdaptiveBatchController — rate-limit protection, DoS vectors,
configuration validation, and state isolation.

These tests verify that the adaptive batching system is safe against API abuse,
configuration-based DoS, and state leakage between providers.

Reference: openspec/changes/adaptive-batching/test-plan.md — SC-01..SC-08
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import AdaptiveBatchingConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.batching.adaptive import AdaptiveBatchController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    min_batch_size: int = 5,
    max_batch_size: int = 50,
    min_batch_delay_sec: float = 3.0,
    max_batch_delay_sec: float = 120.0,
    batch_size_step: int = 5,
    delay_step_sec: float = 2.0,
    rate_limit_divisor: int = 2,
    rate_limit_delay_multiplier: float = 2.0,
    recovery_threshold: int = 5,
    recovery_step_multiplier: float = 2.0,
    failure_rate_threshold: float = 0.3,
) -> AdaptiveBatchingConfig:
    """Create an AdaptiveBatchingConfig with sensible defaults for tests."""
    return AdaptiveBatchingConfig(
        min_batch_size=min_batch_size,
        max_batch_size=max_batch_size,
        min_batch_delay_sec=min_batch_delay_sec,
        max_batch_delay_sec=max_batch_delay_sec,
        batch_size_step=batch_size_step,
        delay_step_sec=delay_step_sec,
        rate_limit_divisor=rate_limit_divisor,
        rate_limit_delay_multiplier=rate_limit_delay_multiplier,
        recovery_threshold=recovery_threshold,
        recovery_step_multiplier=recovery_step_multiplier,
        failure_rate_threshold=failure_rate_threshold,
    )


def _make_controller(
    initial_batch_size: int = 30,
    initial_batch_delay: float = 15.0,
    config: AdaptiveBatchingConfig | None = None,
) -> AdaptiveBatchController:
    """Create an AdaptiveBatchController with the given config and initial values."""
    if config is None:
        config = _make_config()
    return AdaptiveBatchController(
        config=config,
        initial_batch_size=initial_batch_size,
        initial_batch_delay=initial_batch_delay,
    )


def _success_results(count: int) -> list[CheckResult]:
    """Create a list of successful CheckResult objects."""
    return [CheckResult.success() for _ in range(count)]


def _rate_limited_results(count: int) -> list[CheckResult]:
    """Create a list of rate-limited CheckResult objects."""
    return [CheckResult.fail(reason=ErrorReason.RATE_LIMITED) for _ in range(count)]


def _fatal_results(reason: ErrorReason, count: int) -> list[CheckResult]:
    """Create a list of fatal-error CheckResult objects."""
    return [CheckResult.fail(reason=reason) for _ in range(count)]


def _transient_results(reason: ErrorReason, count: int) -> list[CheckResult]:
    """Create a list of transient-error CheckResult objects."""
    return [CheckResult.fail(reason=reason) for _ in range(count)]


# ---------------------------------------------------------------------------
# SC-01: Rate-limited backoff prevents API abuse
# ---------------------------------------------------------------------------


class TestSC01RateLimitedBackoff:
    """
    Provider constantly rate-limits. Controller should:
    - batch_size //= 2 each cycle
    - delay *= 2 each cycle
    - until min_batch_size and max_batch_delay
    - System never sends more than min_batch_size keys per batch at
      persistent rate-limits.
    """

    def test_batch_size_halves_each_rate_limit_cycle(self) -> None:
        """batch_size //= 2 on each rate-limited report until min_batch_size."""
        config = _make_config(min_batch_size=5, max_batch_size=50)
        ctrl = _make_controller(initial_batch_size=30, config=config)

        # Cycle 1: 30 → 15
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_size == 15

        # Cycle 2: 15 → 7  (15 // 2 = 7)
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_size == 7

        # Cycle 3: 7 → 3 capped to min_batch_size=5  (7 // 2 = 3, max(3,5)=5)
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_size == 5

    def test_delay_doubles_each_rate_limit_cycle(self) -> None:
        """delay *= 2 on each rate-limited report until max_batch_delay."""
        config = _make_config(
            min_batch_delay_sec=3.0, max_batch_delay_sec=60.0,
            rate_limit_delay_multiplier=2.0,
        )
        ctrl = _make_controller(initial_batch_delay=15.0, config=config)

        # Cycle 1: 15 → 30
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_delay == 30.0

        # Cycle 2: 30 → 60  (capped at max_batch_delay)
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_delay == 60.0

        # Cycle 3: 60 → 60  (still capped)
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_delay == 60.0

    def test_stays_at_min_batch_size_under_persistent_rate_limits(self) -> None:
        """After reaching min_batch_size, further rate-limits don't reduce it."""
        config = _make_config(min_batch_size=5, max_batch_size=50)
        ctrl = _make_controller(initial_batch_size=30, config=config)

        # Drive down to min_batch_size
        for _ in range(10):
            ctrl.report_batch_result(_rate_limited_results(1))

        assert ctrl.batch_size == 5

        # More rate-limits — stays at 5
        for _ in range(5):
            ctrl.report_batch_result(_rate_limited_results(1))

        assert ctrl.batch_size == 5

    def test_consecutive_successes_reset_on_rate_limit(self) -> None:
        """Rate-limited events reset consecutive_successes to 0."""
        config = _make_config()
        ctrl = _make_controller(config=config)

        # Build up some successes
        for _ in range(3):
            ctrl.report_batch_result(_success_results(10))

        assert ctrl.consecutive_successes == 3

        # One rate-limit resets it
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.consecutive_successes == 0


# ---------------------------------------------------------------------------
# SC-02: Recovery after rate-limited — gradual ramp-up
# ---------------------------------------------------------------------------


class TestSC02GradualRampUpAfterRateLimit:
    """
    After series of rate-limits (batch_size=5, delay=60), series of successes
    begins. Verify ramp-up is gradual: +5 per success, not a jump back to 30.
    This prevents repeat rate-limit.
    """

    def test_ramp_up_is_gradual_after_backoff(self) -> None:
        """Each success adds batch_size_step (5), not a jump back to initial."""
        config = _make_config(
            min_batch_size=5,
            max_batch_size=50,
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            batch_size_step=5,
            delay_step_sec=2.0,
        )
        ctrl = _make_controller(
            initial_batch_size=30, initial_batch_delay=15.0, config=config,
        )

        # Drive to min via rate-limits
        for _ in range(10):
            ctrl.report_batch_result(_rate_limited_results(1))

        assert ctrl.batch_size == 5
        assert ctrl.batch_delay == 60.0

        # Success 1: 5 → 10
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_size == 10
        assert ctrl.batch_delay == 58.0  # 60 - 2.0

        # Success 2: 10 → 15
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_size == 15
        assert ctrl.batch_delay == 56.0  # 58 - 2.0

        # Success 3: 15 → 20
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_size == 20
        assert ctrl.batch_delay == 54.0  # 56 - 2.0

        # Not a jump back to 30
        assert ctrl.batch_size < 30

    def test_ramp_up_does_not_jump_to_initial(self) -> None:
        """After 3 successes, batch_size is still well below initial 30."""
        config = _make_config(min_batch_size=5, max_batch_size=50, batch_size_step=5)
        ctrl = _make_controller(initial_batch_size=30, config=config)

        # Drive to min
        for _ in range(10):
            ctrl.report_batch_result(_rate_limited_results(1))

        assert ctrl.batch_size == 5

        # 3 successes → 5+3*5 = 20, still < 30
        for _ in range(3):
            ctrl.report_batch_result(_success_results(10))

        assert ctrl.batch_size == 20
        assert ctrl.batch_size < 30


# ---------------------------------------------------------------------------
# SC-03: min_batch_delay ensures minimum pause
# ---------------------------------------------------------------------------


class TestSC03MinBatchDelayFloor:
    """
    Even with 5+ consecutive successes, batch_delay never drops below
    min_batch_delay (3.0s). Verify impossible to completely remove delay
    between batches.
    """

    def test_delay_never_drops_below_min_batch_delay(self) -> None:
        """After many successes, batch_delay stays at min_batch_delay_sec."""
        config = _make_config(
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            delay_step_sec=2.0,
        )
        ctrl = _make_controller(initial_batch_delay=15.0, config=config)

        # Successes reduce delay by 2.0 each time
        # 15 → 13 → 11 → 9 → 7 → 5 → 3 (capped)
        for i in range(6):
            ctrl.report_batch_result(_success_results(10))

        assert ctrl.batch_delay == 3.0

        # More successes — stays at 3.0
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_delay == 3.0

        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_delay == 3.0

    def test_aggressive_ramp_up_still_respects_min_delay(self) -> None:
        """Even with recovery_step_multiplier=2.0 (aggressive ramp-up),
        delay cannot go below min_batch_delay_sec."""
        config = _make_config(
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            delay_step_sec=2.0,
            recovery_threshold=5,
            recovery_step_multiplier=2.0,
        )
        ctrl = _make_controller(initial_batch_delay=7.0, config=config)

        # 5 successes to trigger aggressive ramp-up
        for _ in range(5):
            ctrl.report_batch_result(_success_results(10))

        # After 5 successes: delay went 7→5→3→3→3→3 (capped at 3.0 each time after hitting floor)
        # The aggressive step is 2*2.0=4.0, but max(7-4, 3)=3 on 1st success already
        # Let's verify it stays at 3.0
        assert ctrl.batch_delay == 3.0

        # 6th success with aggressive multiplier: delay_step * 2.0 = 4.0
        # max(3.0 - 4.0, 3.0) = 3.0
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_delay == 3.0


# ---------------------------------------------------------------------------
# SC-04: max_batch_delay prevents infinite backoff
# ---------------------------------------------------------------------------


class TestSC04MaxBatchDelayCeiling:
    """
    With persistent rate-limits, delay *= 2 capped at max_batch_delay.
    Verify system doesn't freeze — always continues with min batch.
    """

    def test_delay_capped_at_max_batch_delay(self) -> None:
        """delay *= 2 never exceeds max_batch_delay_sec."""
        config = _make_config(
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            rate_limit_delay_multiplier=2.0,
        )
        ctrl = _make_controller(initial_batch_delay=40.0, config=config)

        # 40 * 2 = 80 → capped at 60
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_delay == 60.0

        # 60 * 2 = 120 → still capped at 60
        ctrl.report_batch_result(_rate_limited_results(1))
        assert ctrl.batch_delay == 60.0

    def test_system_does_not_freeze_at_max_delay(self) -> None:
        """Even at max_batch_delay, the controller still operates
        (batch_size at min, but system continues)."""
        config = _make_config(
            min_batch_size=5,
            max_batch_size=50,
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
        )
        ctrl = _make_controller(initial_batch_size=30, initial_batch_delay=15.0, config=config)

        # Drive to extremes
        for _ in range(20):
            ctrl.report_batch_result(_rate_limited_results(1))

        # System hasn't frozen — batch_size is at min, delay at max
        assert ctrl.batch_size == 5
        assert ctrl.batch_delay == 60.0

        # Controller is still functional — a success will start ramp-up
        ctrl.report_batch_result(_success_results(10))
        assert ctrl.batch_size == 10  # 5 + 5
        assert ctrl.batch_delay == 58.0  # 60 - 2.0


# ---------------------------------------------------------------------------
# SC-05: Configuration with extreme values — validation
# ---------------------------------------------------------------------------


class TestSC05ExtremeConfigValues:
    """
    Create AdaptiveBatchingConfig(min_batch_size=1, max_batch_size=10000,
    min_batch_delay_sec=0.01, max_batch_delay_sec=3600).
    Verify Pydantic allows it (bounds are valid integers/floats).
    """

    def test_extreme_values_are_accepted(self) -> None:
        """Pydantic allows extreme but valid config values."""
        config = AdaptiveBatchingConfig(
            min_batch_size=1,
            max_batch_size=10000,
            min_batch_delay_sec=0.01,
            max_batch_delay_sec=3600.0,
            batch_size_step=5,
            delay_step_sec=2.0,
            rate_limit_divisor=2,
            rate_limit_delay_multiplier=2.0,
            recovery_threshold=5,
            recovery_step_multiplier=2.0,
            failure_rate_threshold=0.3,
        )
        assert config.min_batch_size == 1
        assert config.max_batch_size == 10000
        assert config.min_batch_delay_sec == 0.01
        assert config.max_batch_delay_sec == 3600.0

    def test_min_batch_size_1_is_valid(self) -> None:
        """min_batch_size=1 is valid (gt=0 constraint satisfied)."""
        config = AdaptiveBatchingConfig(
            min_batch_size=1,
            max_batch_size=2,
        )
        assert config.min_batch_size == 1

    def test_very_small_delay_is_valid(self) -> None:
        """min_batch_delay_sec=0.01 is valid (gt=0 constraint satisfied)."""
        config = AdaptiveBatchingConfig(
            min_batch_delay_sec=0.01,
            max_batch_delay_sec=0.02,
        )
        assert config.min_batch_delay_sec == 0.01

    def test_very_large_max_delay_is_valid(self) -> None:
        """max_batch_delay_sec=3600 (1 hour) is valid."""
        config = AdaptiveBatchingConfig(
            min_batch_delay_sec=1.0,
            max_batch_delay_sec=3600.0,
        )
        assert config.max_batch_delay_sec == 3600.0


# ---------------------------------------------------------------------------
# SC-06: DoS via config — min_batch_delay=0.0
# ---------------------------------------------------------------------------


class TestSC06DosViaZeroDelayConfig:
    """
    If min_batch_delay_sec=0.0 is allowed, system could send batches without
    delay. Verify Pydantic schema requires min_batch_delay_sec > 0 (gt=0
    constraint).
    """

    def test_min_batch_delay_zero_rejected(self) -> None:
        """min_batch_delay_sec=0.0 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(
                min_batch_delay_sec=0.0,
                max_batch_delay_sec=60.0,
            )

    def test_min_batch_delay_negative_rejected(self) -> None:
        """min_batch_delay_sec=-1.0 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(
                min_batch_delay_sec=-1.0,
                max_batch_delay_sec=60.0,
            )

    def test_min_batch_size_zero_rejected(self) -> None:
        """min_batch_size=0 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(
                min_batch_size=0,
                max_batch_size=50,
            )

    def test_min_batch_size_negative_rejected(self) -> None:
        """min_batch_size=-1 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(
                min_batch_size=-1,
                max_batch_size=50,
            )

    def test_delay_step_zero_rejected(self) -> None:
        """delay_step_sec=0.0 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(delay_step_sec=0.0)

    def test_batch_size_step_zero_rejected(self) -> None:
        """batch_size_step=0 raises ValidationError (gt=0)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(batch_size_step=0)

    def test_rate_limit_divisor_one_rejected(self) -> None:
        """rate_limit_divisor=1 raises ValidationError (gt=1 — divisor must be >1)."""
        with pytest.raises(ValidationError):
            AdaptiveBatchingConfig(rate_limit_divisor=1)


# ---------------------------------------------------------------------------
# SC-07: Fatal errors don't cause backoff — correctness
# ---------------------------------------------------------------------------


class TestSC07FatalErrorsIgnored:
    """
    INVALID_KEY, NO_ACCESS, NO_QUOTA, NO_MODEL are per-key problems.
    Verify fatal errors are fully ignored in failure rate.
    """

    def test_all_fatal_results_trigger_ramp_up(self) -> None:
        """A batch with only fatal errors is treated as success for ramp-up."""
        config = _make_config(batch_size_step=5, delay_step_sec=2.0)
        ctrl = _make_controller(initial_batch_size=30, initial_batch_delay=15.0, config=config)

        # All 10 results are fatal (INVALID_KEY)
        results = _fatal_results(ErrorReason.INVALID_KEY, 10)
        ctrl.report_batch_result(results)

        # Fatal errors are ignored → non_fatal_total=0 → no transient rate
        # → no rate_limited → ramp-up applied
        assert ctrl.batch_size == 35  # 30 + 5
        assert ctrl.batch_delay == 13.0  # 15 - 2.0
        assert ctrl.consecutive_successes == 1

    def test_each_fatal_error_type_ignored(self) -> None:
        """All four fatal error types (INVALID_KEY, NO_ACCESS, NO_QUOTA, NO_MODEL)
        are individually ignored and trigger ramp-up."""
        config = _make_config(batch_size_step=5)
        fatal_reasons = [
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
            ErrorReason.NO_QUOTA,
            ErrorReason.NO_MODEL,
        ]

        for reason in fatal_reasons:
            ctrl = _make_controller(initial_batch_size=30, config=config)
            ctrl.report_batch_result(_fatal_results(reason, 5))
            assert ctrl.batch_size == 35, f"{reason} should be ignored (ramp-up applied)"
            assert ctrl.consecutive_successes == 1

    def test_mixed_fatal_and_success_trigger_ramp_up(self) -> None:
        """Fatal + success results: fatal ignored, success triggers ramp-up."""
        config = _make_config(batch_size_step=5)
        ctrl = _make_controller(initial_batch_size=30, config=config)

        results = _fatal_results(ErrorReason.INVALID_KEY, 3) + _success_results(7)
        ctrl.report_batch_result(results)

        # No rate_limited, transient_rate=0 (no transient), → ramp-up
        assert ctrl.batch_size == 35
        assert ctrl.consecutive_successes == 1

    def test_fatal_errors_excluded_from_transient_rate(self) -> None:
        """Fatal errors are excluded from denominator when computing transient rate.

        total=10, fatal=3, transient=3 → transient_rate = 3/(10-3) = 3/7 ≈ 42.8% > 30%
        → moderate backoff applied.
        """
        config = _make_config(
            min_batch_size=5,
            max_batch_size=50,
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            batch_size_step=5,
            delay_step_sec=2.0,
            failure_rate_threshold=0.3,
        )
        ctrl = _make_controller(initial_batch_size=30, initial_batch_delay=15.0, config=config)

        results = (
            _fatal_results(ErrorReason.INVALID_KEY, 3)
            + _transient_results(ErrorReason.TIMEOUT, 3)
            + _success_results(4)
        )
        ctrl.report_batch_result(results)

        # transient_rate = 3/(10-3) = 42.8% > 30% → moderate backoff
        assert ctrl.batch_size == 25  # 30 - 5
        assert ctrl.batch_delay == 17.0  # 15 + 2.0
        assert ctrl.consecutive_successes == 0

    def test_rate_limited_takes_priority_over_fatal(self) -> None:
        """Mixed fatal + rate_limited: rate_limited triggers aggressive backoff,
        fatal is irrelevant."""
        config = _make_config(
            min_batch_size=5,
            max_batch_size=50,
            rate_limit_divisor=2,
            rate_limit_delay_multiplier=2.0,
        )
        ctrl = _make_controller(initial_batch_size=30, initial_batch_delay=15.0, config=config)

        results = (
            _fatal_results(ErrorReason.INVALID_KEY, 2)
            + _rate_limited_results(1)
            + _success_results(7)
        )
        ctrl.report_batch_result(results)

        # Rate-limited takes priority → aggressive backoff
        assert ctrl.batch_size == 15  # 30 // 2
        assert ctrl.batch_delay == 30.0  # 15 * 2
        assert ctrl.consecutive_successes == 0


# ---------------------------------------------------------------------------
# SC-08: Controller state doesn't leak between providers
# ---------------------------------------------------------------------------


class TestSC08StateIsolationBetweenProviders:
    """
    Two controllers for different providers. Verify state (batch_size, delay,
    consecutive_successes) of one doesn't affect the other.
    """

    def test_independent_batch_size(self) -> None:
        """Rate-limiting one controller doesn't affect the other's batch_size."""
        config = _make_config(min_batch_size=5, max_batch_size=50)
        ctrl_openai = _make_controller(initial_batch_size=30, config=config)
        ctrl_gemini = _make_controller(initial_batch_size=30, config=config)

        # Rate-limit openai
        ctrl_openai.report_batch_result(_rate_limited_results(1))
        assert ctrl_openai.batch_size == 15

        # Gemini unaffected
        assert ctrl_gemini.batch_size == 30

    def test_independent_batch_delay(self) -> None:
        """Rate-limiting one controller doesn't affect the other's batch_delay."""
        config = _make_config(min_batch_delay_sec=3.0, max_batch_delay_sec=60.0)
        ctrl_openai = _make_controller(initial_batch_delay=15.0, config=config)
        ctrl_gemini = _make_controller(initial_batch_delay=15.0, config=config)

        # Rate-limit openai
        ctrl_openai.report_batch_result(_rate_limited_results(1))
        assert ctrl_openai.batch_delay == 30.0

        # Gemini unaffected
        assert ctrl_gemini.batch_delay == 15.0

    def test_independent_consecutive_successes(self) -> None:
        """Successes on one controller don't affect the other's consecutive_successes."""
        config = _make_config()
        ctrl_openai = _make_controller(config=config)
        ctrl_gemini = _make_controller(config=config)

        # OpenAI gets 3 successes
        for _ in range(3):
            ctrl_openai.report_batch_result(_success_results(10))

        assert ctrl_openai.consecutive_successes == 3
        assert ctrl_gemini.consecutive_successes == 0

        # Gemini gets a rate-limit
        ctrl_gemini.report_batch_result(_rate_limited_results(1))
        assert ctrl_gemini.consecutive_successes == 0
        assert ctrl_openai.consecutive_successes == 3  # unaffected

    def test_full_independence_scenario(self) -> None:
        """
        Full scenario: openai is rate-limited and backs off, gemini ramps up.
        Neither affects the other.
        """
        config = _make_config(
            min_batch_size=5,
            max_batch_size=50,
            min_batch_delay_sec=3.0,
            max_batch_delay_sec=60.0,
            batch_size_step=5,
            delay_step_sec=2.0,
        )
        ctrl_openai = _make_controller(
            initial_batch_size=30, initial_batch_delay=15.0, config=config,
        )
        ctrl_gemini = _make_controller(
            initial_batch_size=30, initial_batch_delay=15.0, config=config,
        )

        # OpenAI: 2 rate-limits
        ctrl_openai.report_batch_result(_rate_limited_results(1))
        ctrl_openai.report_batch_result(_rate_limited_results(1))
        assert ctrl_openai.batch_size == 7
        assert ctrl_openai.batch_delay == 60.0  # 15*2=30, 30*2=60
        assert ctrl_openai.consecutive_successes == 0

        # Gemini: 3 successes
        for _ in range(3):
            ctrl_gemini.report_batch_result(_success_results(10))
        assert ctrl_gemini.batch_size == 45  # 30+5+5+5
        assert ctrl_gemini.batch_delay == 9.0  # 15-2-2-2
        assert ctrl_gemini.consecutive_successes == 3

        # Cross-check: openai state unchanged by gemini successes
        assert ctrl_openai.batch_size == 7
        assert ctrl_openai.batch_delay == 60.0
        assert ctrl_openai.consecutive_successes == 0

    def test_different_configs_dont_interact(self) -> None:
        """Controllers with different configs are fully independent."""
        config_openai = _make_config(
            min_batch_size=5, max_batch_size=50,
            batch_size_step=5, delay_step_sec=2.0,
        )
        config_gemini = _make_config(
            min_batch_size=10, max_batch_size=100,
            batch_size_step=10, delay_step_sec=5.0,
        )
        ctrl_openai = _make_controller(
            initial_batch_size=30, initial_batch_delay=15.0, config=config_openai,
        )
        ctrl_gemini = _make_controller(
            initial_batch_size=50, initial_batch_delay=20.0, config=config_gemini,
        )

        # OpenAI success → +5
        ctrl_openai.report_batch_result(_success_results(10))
        assert ctrl_openai.batch_size == 35
        assert ctrl_openai.batch_delay == 13.0

        # Gemini success → +10
        ctrl_gemini.report_batch_result(_success_results(10))
        assert ctrl_gemini.batch_size == 60
        assert ctrl_gemini.batch_delay == 15.0  # 20 - 5

        # Neither affected the other
        assert ctrl_openai.batch_size == 35
        assert ctrl_openai.batch_delay == 13.0