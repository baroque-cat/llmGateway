"""
Unified exception-handling decorator.

Async-aware, respects existing error conventions (ErrorReason, exc_info on ERROR+).
Import path: ``from src.core.exception_handler import handle_exceptions``.

This module lives in ``core/`` and imports only standard library modules,
preserving the project's architectural rule that ``core/`` must not depend on
``services/``, ``config/``, ``providers/``, or ``db/``.
"""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


def handle_exceptions(
    default_result: Any = None,
    log_level: str = "error",
    reraise: bool = False,
) -> Callable[[F], F]:
    """
    Decorator that wraps a function with uniform exception logging and recovery.

    Automatically detects whether the wrapped function is synchronous or
    asynchronous and applies the appropriate wrapper.

    Args:
        default_result: Value returned when an exception is caught (only used
            when ``reraise=False``, the default).
        log_level: Logging level name for the exception message (e.g. ``"error"``,
            ``"warning"``, ``"critical"``). When the level is ``"error"`` or
            ``"critical"``, a full traceback is also logged at DEBUG level with
            ``exc_info=True``.
        reraise: If ``True``, the caught exception is re-raised after logging
            instead of returning ``default_result``.

    Returns:
        A decorator that can be applied to both sync and async functions.

    Example::

        @handle_exceptions(default_result=[], log_level="warning")
        async def fetch_items() -> list[str]:
            ...
    """

    def _log(func: Callable[..., Any], exc: Exception, level: str) -> None:
        log_func = getattr(logger, level, logger.error)
        log_func(f"Exception in {func.__qualname__}: {exc}")
        if level in ("error", "critical"):
            logger.debug(
                f"Traceback for {func.__qualname__}:\n...",
                exc_info=True,
            )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                _log(func, exc, log_level)
                if reraise:
                    raise
                return default_result

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                _log(func, exc, log_level)
                if reraise:
                    raise
                return default_result

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
