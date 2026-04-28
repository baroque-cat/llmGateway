"""
Utility for retrying database operations.

Provides the ``AsyncRetrier`` class, which wraps async DB operations and
automatically retries them on transient connection errors (connection drop,
protocol error, pool exhaustion, deadlock).

Uses exponential backoff with optional jitter to prevent thundering herd.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

try:
    import asyncpg

    _has_asyncpg = True
except ImportError:  # pragma: no cover
    asyncpg = None
    _has_asyncpg = False

logger = logging.getLogger(__name__)

T = TypeVar("T")

if _has_asyncpg:
    # Set of transient asyncpg exceptions worth retrying.
    # Fixed tuple — not configurable via YAML so users don't need
    # to know about internal driver classes.
    _db_retryable = (
        asyncpg.exceptions.ConnectionDoesNotExistError,  # type: ignore[union-attr]
        asyncpg.exceptions.InterfaceError,  # type: ignore[union-attr]
        asyncpg.exceptions.TooManyConnectionsError,  # type: ignore[union-attr]
        asyncpg.exceptions.DeadlockDetectedError,  # type: ignore[union-attr]
    )
else:
    _db_retryable = ()

DB_RETRYABLE: tuple[type[Exception], ...] = _db_retryable


def _safe_exc_str(exc: Exception) -> str:
    """Safe string representation of an exception.

    Some asyncpg exceptions may not have ``args[0]``,
    and calling ``str(exc)`` or formatting via ``%s`` will fail
    with ``IndexError``.
    """
    try:
        return str(exc)
    except Exception:
        return repr(exc)


class AsyncRetrier:
    """
    Async retry mechanism for database operations.

    Created with configuration from ``DatabaseRetryConfig`` and injected
    into ``KeyProbe`` via constructor (Dependency Injection).

    Each retry attempt is logged at WARNING level; when all attempts
    are exhausted — ERROR.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_sec: float = 1.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        retryable: tuple[type[Exception], ...] = DB_RETRYABLE,
    ) -> None:
        """
        Initialize the retry mechanism.

        Args:
            max_attempts: Maximum number of attempts (including the first).
                Limited by schema validation (1..10).
            base_delay_sec: Base delay before the first retry (seconds).
            backoff_factor: Multiplier for exponential backoff.
                ``delay = base * factor^(attempt)``.
            jitter: Whether to add a random multiplier [0.5, 1.5] to the delay.
            retryable: Tuple of exception classes that should be retried.
                Default is ``DB_RETRYABLE`` (4 transient asyncpg classes).
        """
        self._max_attempts = max_attempts
        self._base_delay_sec = base_delay_sec
        self._backoff_factor = backoff_factor
        self._jitter = jitter
        self._retryable = retryable

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        """
        Execute an operation with automatic retries.

        Args:
            operation: Coroutine factory (``Callable[[], Awaitable[T]]``).
                Called anew on each attempt, since an asyncio coroutine
                can only be awaited once.

        Returns:
            Result of the operation (type T).

        Raises:
            The last exception after all attempts are exhausted.
            Non-retryable exceptions are re-raised immediately without retry.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                last_exception = exc

                # Non-retryable exceptions are re-raised immediately
                if not isinstance(exc, self._retryable):
                    logger.error(
                        "DB operation failed with non-retryable error: %s(%s)",
                        type(exc).__name__,
                        _safe_exc_str(exc),
                    )
                    raise

                if attempt == self._max_attempts:
                    logger.error(
                        "DB operation failed after %d attempts: %s(%s)",
                        self._max_attempts,
                        type(exc).__name__,
                        _safe_exc_str(exc),
                    )
                    raise

                delay = self._compute_delay(attempt)
                logger.warning(
                    "DB operation failed (attempt %d/%d), retrying in %.1fs: %s(%s)",
                    attempt,
                    self._max_attempts,
                    delay,
                    type(exc).__name__,
                    _safe_exc_str(exc),
                )
                await asyncio.sleep(delay)

        # Unreachable, but keeps mypy happy
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("AsyncRetrier.execute: unreachable state")

    def _compute_delay(self, attempt: int) -> float:
        """
        Compute the delay before the next attempt.

        Formula: ``base_delay_sec * backoff_factor^(attempt-1)``.
        If ``jitter=True``, the result is multiplied by a random factor
        in range [0.5, 1.5].

        Args:
            attempt: Current (failed) attempt number (1-based).

        Returns:
            Delay in seconds (float).
        """
        delay = self._base_delay_sec * (self._backoff_factor ** (attempt - 1))
        if self._jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay
