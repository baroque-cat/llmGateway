"""Non-blocking semaphore extension for httpcore's AsyncSemaphore.

Adds ``acquire_nowait()`` — an atomic non-blocking slot acquisition that
returns ``False`` when all slots are occupied instead of blocking forever.

This is part of the full PR #1088 backport: using atomic acquire_nowait()
instead of the current monkey-patch's two-step check (``.available`` property
followed by ``.acquire()``) eliminates the theoretical race window.

The parent class ``AsyncSemaphore`` is left unchanged; all existing methods
(``acquire()``, ``release()``, ``setup()``) are inherited.
"""

from __future__ import annotations

from httpcore._synchronization import AsyncSemaphore


class NonBlockingSemaphore(AsyncSemaphore):
    """AsyncSemaphore with non-blocking ``acquire_nowait()``.

    Inherits ``acquire()``, ``release()``, and ``setup()`` unchanged from
    :class:`httpcore._synchronization.AsyncSemaphore`.

    Only one method is added — ``acquire_nowait()`` — which attempts to
    acquire a slot without blocking.  Returns ``True`` on success,
    ``False`` if no slots are available.
    """

    def acquire_nowait(self) -> bool:
        """Try to acquire a slot without blocking.

        Returns:
            ``True`` if a slot was acquired, ``False`` if the semaphore
            is full and no slots are available.
        """
        if not self._backend:
            self.setup()

        if self._backend == "trio":
            import trio  # type: ignore[reportMissingImports]

            try:
                self._trio_semaphore.acquire_nowait()  # type: ignore[reportUnknownMemberType]
            except trio.WouldBlock:  # type: ignore[reportUnknownMemberType]
                return False
            return True

        if self._backend == "asyncio":
            import anyio

            try:
                self._anyio_semaphore.acquire_nowait()
            except anyio.WouldBlock:
                return False
            return True

        return False
