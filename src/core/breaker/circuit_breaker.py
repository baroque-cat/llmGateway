"""
Per-provider circuit breaker state machine for the gateway sticky-key mode.

This module implements ``KeyCircuitBreaker`` — a pure synchronous controller
that detects provider-wide failure waves and temporarily suspends retry
pressure. It follows the ``AdaptiveBatchController`` precedent: a pure state
machine in ``core/`` (pyright strict), parameters in a frozen dataclass
(:class:`~src.core.models.CircuitBreakerParams`), observability counters as
public attributes, and all wiring performed by the service layer.

The breaker consumes the *final refined* ``ErrorReason`` (the output of
``error_parsing``) as the single source of truth. Only failures whose reason
``is_retryable()`` count as wave evidence; successes and non-retryable
failures (fatal, client) occupy window slots without counting toward the
error share.
"""

import time
from collections import deque
from collections.abc import Callable

from src.core.constants import BreakerState, ErrorReason
from src.core.models import CircuitBreakerParams


class KeyCircuitBreaker:
    """
    Synchronous circuit breaker state machine for one provider instance.

    The breaker maintains a count-based sliding window of the most recent
    upstream attempt outcomes (no timers for the error-rate computation) and
    transitions between ``CLOSED``, ``OPEN``, and ``HALF_OPEN`` states:

    - ``CLOSED`` — normal operation. When the window holds at least
      ``min_samples`` outcomes and the retryable-error share reaches
      ``error_rate_threshold``, the breaker opens.
    - ``OPEN`` — a failure wave was detected. Requests are served fail-fast
      (retry loop bypassed) until ``open_duration_sec`` elapses.
    - ``HALF_OPEN`` — the cooldown elapsed. Requests flow as probes;
      ``probe_successes_to_close`` consecutive successes close the breaker,
      any retryable failure re-opens it with the cooldown multiplied by
      ``backoff_factor`` (capped at ``max_open_duration_sec``).

    Time is read through an injectable ``clock`` so tests stay deterministic.
    One instance exists per provider instance per worker process; state is
    in-memory only and resets on worker restart.
    """

    def __init__(
        self,
        params: CircuitBreakerParams,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Initialize the breaker in the ``CLOSED`` state with an empty window.

        Args:
            params: Pure dataclass with the breaker tuning knobs.
            clock: Monotonic time source used for cooldown tracking.
                Injectable for deterministic testing.
        """
        self._params = params
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._window: deque[ErrorReason | None] = deque(maxlen=params.window_size)
        self._opened_at: float = 0.0
        self._current_cooldown: float = params.open_duration_sec
        self._probe_successes: int = 0

        # Counters for observability (exposed for metrics collection)
        self.opened_events: int = 0
        self.closed_events: int = 0
        self.reopened_events: int = 0
        self.fail_fast_events: int = 0

    @property
    def state(self) -> BreakerState:
        """Current breaker state."""
        return self._state

    @property
    def window(self) -> tuple[ErrorReason | None, ...]:
        """Snapshot of the sliding window (``None`` entries are successes)."""
        return tuple(self._window)

    @property
    def current_cooldown(self) -> float:
        """Current OPEN-state cooldown in seconds (grows on re-opens)."""
        return self._current_cooldown

    @property
    def probe_successes(self) -> int:
        """Consecutive successful probes recorded while ``HALF_OPEN``."""
        return self._probe_successes

    def should_fail_fast(self) -> bool:
        """
        Check whether a request must bypass the retry loop (fail-fast).

        Also drives the time-based ``OPEN`` → ``HALF_OPEN`` transition: when
        the cooldown has elapsed, probing resumes and this method returns
        ``False``.

        Returns:
            bool: True while ``OPEN`` with an active cooldown; the fail-fast
            counter is incremented for every such request.
        """
        if self._state is BreakerState.OPEN:
            if self.begin_probe():
                return False
            self.fail_fast_events += 1
            return True
        return False

    def begin_probe(self) -> bool:
        """
        Transition ``OPEN`` → ``HALF_OPEN`` once the cooldown has elapsed.

        Idempotent: a breaker that is already ``HALF_OPEN`` (or ``CLOSED``)
        is left unchanged.

        Returns:
            bool: True if the breaker is ``HALF_OPEN`` after the call, i.e.
            probe traffic may flow.
        """
        if (
            self._state is BreakerState.OPEN
            and self._clock() - self._opened_at >= self._current_cooldown
        ):
            self._state = BreakerState.HALF_OPEN
            self._probe_successes = 0
        return self._state is BreakerState.HALF_OPEN

    def record_result(self, ok: bool, error_reason: ErrorReason | None = None) -> None:
        """
        Record the outcome of an upstream attempt.

        Args:
            ok: True if the attempt succeeded.
            error_reason: Final refined reason on failure (ignored on
                success). ``None`` on failure is treated as ``UNKNOWN``.

        In ``HALF_OPEN`` the outcome is routed to the probe trackers. In
        ``CLOSED`` the outcome is appended to the window and the opening
        condition is evaluated. In ``OPEN`` the outcome is appended (keeping
        the window fresh) but never triggers a transition.
        """
        if self._state is BreakerState.HALF_OPEN:
            if ok:
                self.record_probe_success()
            else:
                self.record_probe_failure(
                    error_reason if error_reason is not None else ErrorReason.UNKNOWN
                )
            return

        reason = (
            None
            if ok
            else (error_reason if error_reason is not None else ErrorReason.UNKNOWN)
        )
        self._window.append(reason)
        if self._state is BreakerState.CLOSED:
            self._evaluate_opening()

    def record_probe_success(self) -> None:
        """
        Record a successful ``HALF_OPEN`` probe attempt.

        After ``probe_successes_to_close`` consecutive successes the breaker
        closes: the window is cleared and the cooldown resets to the base
        ``open_duration_sec``. No-op outside ``HALF_OPEN``.
        """
        if self._state is not BreakerState.HALF_OPEN:
            return
        self._window.append(None)
        self._probe_successes += 1
        if self._probe_successes >= self._params.probe_successes_to_close:
            self._close()

    def record_probe_failure(self, error_reason: ErrorReason) -> None:
        """
        Record a failed ``HALF_OPEN`` probe attempt.

        Retryable failures re-open the breaker with the cooldown multiplied
        by ``backoff_factor`` (capped at ``max_open_duration_sec``).
        Non-retryable failures only reset the consecutive-success streak.
        No-op outside ``HALF_OPEN``.

        Args:
            error_reason: Final refined reason of the failed probe.
        """
        if self._state is not BreakerState.HALF_OPEN:
            return
        self._window.append(error_reason)
        self._probe_successes = 0
        if error_reason.is_retryable():
            self._reopen()

    def _evaluate_opening(self) -> None:
        """Open the breaker if the window shows a retryable-error wave."""
        if len(self._window) < self._params.min_samples:
            return
        retryable = sum(
            1 for reason in self._window if reason is not None and reason.is_retryable()
        )
        error_rate = retryable / len(self._window)
        if error_rate >= self._params.error_rate_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = self._clock()
            self._probe_successes = 0
            self.opened_events += 1

    def _reopen(self) -> None:
        """Return from ``HALF_OPEN`` to ``OPEN`` with exponential cooldown."""
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._probe_successes = 0
        self._current_cooldown = min(
            self._current_cooldown * self._params.backoff_factor,
            self._params.max_open_duration_sec,
        )
        self.reopened_events += 1

    def _close(self) -> None:
        """Close the breaker after a successful probe sequence."""
        self._state = BreakerState.CLOSED
        self._window.clear()
        self._probe_successes = 0
        self._current_cooldown = self._params.open_duration_sec
        self.closed_events += 1
