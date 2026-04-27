"""
Self-tuning batch controller for background worker probes.

This module implements the adaptive batch sizing algorithm that replaces
fixed ``batch_size`` / ``batch_delay_sec`` with a controller that adjusts
throughput based on the results of each completed batch.
"""

from src.config.schemas import AdaptiveBatchingConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult


class AdaptiveBatchController:
    """
    Synchronous, self-tuning controller for batch size and delay.

    This controller manages the throughput for a single provider's probe
    cycle by adjusting ``batch_size`` (how many keys are checked in parallel)
    and ``batch_delay`` (the pause between consecutive batches) based on
    the classification of check results in the just-completed batch.

    The classification scheme recognises three categories:

    1. **rate_limited** — ``ErrorReason.RATE_LIMITED``:
       Immediate aggressive backoff: ``batch_size //= divisor``,
       ``delay *= multiplier``.

    2. **transient** — retryable errors that are *not* rate-limit:
       Moderate backoff when the transient proportion of *non-fatal*
       results exceeds ``failure_rate_threshold``:
       ``batch_size -= step``, ``delay += step``.

    3. **fatal** — ``ErrorReason.is_fatal()`` (e.g. INVALID_KEY):
       Completely ignored — these are per-key problems, not provider issues.

    After ``recovery_threshold`` consecutive successful batches the step
    multiplier doubles, enabling faster ramp-up back to peak throughput.

    .. note::
       The controller is intentionally synchronous — it has no I/O and is
       called sequentially for a given provider, so no locks are needed.
    """

    def __init__(
        self,
        config: AdaptiveBatchingConfig,
        initial_batch_size: int,
        initial_batch_delay: float,
    ) -> None:
        """
        Initialise the controller.

        Args:
            config: Validated adaptive batching configuration.
            initial_batch_size: Starting batch size, capped to
                ``[min_batch_size, max_batch_size]``.
            initial_batch_delay: Starting delay in seconds, capped to
                ``[min_batch_delay_sec, max_batch_delay_sec]``.
        """
        self._config = config
        self._batch_size = max(
            config.min_batch_size, min(config.max_batch_size, initial_batch_size)
        )
        self._batch_delay = max(
            config.min_batch_delay_sec,
            min(config.max_batch_delay_sec, initial_batch_delay),
        )
        self._consecutive_successes = 0

        # Counters for observability (exposed for metrics collection)
        self.rate_limit_events: int = 0
        self.backoff_events: int = 0
        self.recovery_events: int = 0

    @property
    def batch_size(self) -> int:
        """Current (dynamic) batch size."""
        return self._batch_size

    @property
    def batch_delay(self) -> float:
        """Current (dynamic) delay in seconds between batches."""
        return self._batch_delay

    @property
    def consecutive_successes(self) -> int:
        """Number of consecutive successful batches (for recovery tracking)."""
        return self._consecutive_successes

    def report_batch_result(self, results: list[CheckResult]) -> None:
        """
        Update controller state based on the results of a completed batch.

        Args:
            results: The final ``CheckResult`` objects for every resource in
                the just-completed batch (after all verification logic).

        The algorithm applies one of three strategies in priority order:

        1. **Aggressive backoff** — triggered by *any* ``RATE_LIMITED``.
        2. **Moderate backoff** — triggered when transient-error proportion
           of non-fatal results exceeds ``failure_rate_threshold``.
        3. **Ramp-up** — applied when neither of the above triggers.
        """
        total = len(results)
        if total == 0:
            return  # no-op for empty batch

        # --- Classification ---
        fatal = 0
        rate_limited = 0
        transient = 0

        for r in results:
            reason = r.error_reason
            if reason.is_fatal():
                fatal += 1
            elif reason == ErrorReason.RATE_LIMITED:
                rate_limited += 1
            elif reason.is_retryable():
                transient += 1
            # other (BAD_REQUEST, UNKNOWN, success) — ignored

        non_fatal_total = total - fatal

        # --- Priority 1: Rate-limited → aggressive backoff ---
        if rate_limited > 0:
            self._batch_size = max(
                self._config.min_batch_size,
                self._batch_size // self._config.rate_limit_divisor,
            )
            self._batch_delay = min(
                self._config.max_batch_delay_sec,
                self._batch_delay * self._config.rate_limit_delay_multiplier,
            )
            self._consecutive_successes = 0
            self.rate_limit_events += 1
            return

        # --- Priority 2: Transient-error proportion > threshold → moderate backoff ---
        transient_rate = transient / non_fatal_total if non_fatal_total > 0 else 0.0

        if transient_rate > self._config.failure_rate_threshold:
            self._batch_size = max(
                self._config.min_batch_size,
                self._batch_size - self._config.batch_size_step,
            )
            self._batch_delay = min(
                self._config.max_batch_delay_sec,
                self._batch_delay + self._config.delay_step_sec,
            )
            self._consecutive_successes = 0
            self.backoff_events += 1
            return

        # --- Priority 3: Success → ramp-up ---
        self._consecutive_successes += 1
        step_mult = (
            self._config.recovery_step_multiplier
            if self._consecutive_successes >= self._config.recovery_threshold
            else 1.0
        )

        self._batch_size = min(
            self._config.max_batch_size,
            self._batch_size + int(self._config.batch_size_step * step_mult),
        )
        self._batch_delay = max(
            self._config.min_batch_delay_sec,
            self._batch_delay - self._config.delay_step_sec * step_mult,
        )
        self.recovery_events += 1
