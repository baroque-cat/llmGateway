"""
Утилита для повторных попыток выполнения операций с базой данных.

Предоставляет класс ``AsyncRetrier``, который оборачивает асинхронные
DB-операции и автоматически повторяет их при transient-ошибках соединения
(разрыв соединения, ошибка протокола, исчерпание пула, deadlock).

Использует экспоненциальный backoff с опциональным jitter для предотвращения
thundering herd.
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
    # Набор transient-исключений asyncpg, которые имеет смысл ретраить.
    # Фиксированный tuple — не конфигурируется через YAML, чтобы пользователь
    # не зависел от знания внутренних классов драйвера.
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
    """Безопасное строковое представление исключения.

    Некоторые исключения asyncpg могут не иметь ``args[0]``,
    и вызов ``str(exc)`` или форматирование через ``%s`` упадёт
    с ``IndexError``.
    """
    try:
        return str(exc)
    except Exception:
        return repr(exc)


class AsyncRetrier:
    """
    Асинхронный retry-механизм для операций с базой данных.

    Создаётся с конфигурацией из ``DatabaseRetryConfig`` и внедряется
    в ``KeyProbe`` через конструктор (Dependency Injection).

    Каждая повторная попытка логируется на уровне WARNING; при исчерпании
    всех попыток — ERROR.
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
        Инициализация retry-механизма.

        Args:
            max_attempts: Максимальное число попыток (включая первую).
                Ограничено schema-валидацией (1..10).
            base_delay_sec: Базовая задержка перед первой повторной попыткой (сек).
            backoff_factor: Множитель экспоненциального backoff.
                ``delay = base * factor^(attempt)``.
            jitter: Добавлять ли случайный множитель [0.5, 1.5] к задержке.
            retryable: Кортеж классов исключений, которые следует ретраить.
                По умолчанию — ``DB_RETRYABLE`` (4 transient-класса asyncpg).
        """
        self._max_attempts = max_attempts
        self._base_delay_sec = base_delay_sec
        self._backoff_factor = backoff_factor
        self._jitter = jitter
        self._retryable = retryable

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        """
        Выполнить операцию с автоматическими повторными попытками.

        Args:
            operation: Фабрика корутин (``Callable[[], Awaitable[T]]``).
                Вызывается заново на каждой попытке, так как asyncio coroutine
                может быть awaited только один раз.

        Returns:
            Результат выполнения операции (тип T).

        Raises:
            Последнее исключение после исчерпания всех попыток.
            Non-retryable исключения пробрасываются сразу без retry.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                last_exception = exc

                # Non-retryable исключения пробрасываем сразу
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

        # Unreachable, но для mypy
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("AsyncRetrier.execute: unreachable state")

    def _compute_delay(self, attempt: int) -> float:
        """
        Вычислить задержку перед следующей попыткой.

        Формула: ``base_delay_sec * backoff_factor^(attempt-1)``.
        Если ``jitter=True``, результат умножается на случайный коэффициент
        в диапазоне [0.5, 1.5].

        Args:
            attempt: Номер текущей (неудачной) попытки (1-based).

        Returns:
            Задержка в секундах (float).
        """
        delay = self._base_delay_sec * (self._backoff_factor ** (attempt - 1))
        if self._jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay
