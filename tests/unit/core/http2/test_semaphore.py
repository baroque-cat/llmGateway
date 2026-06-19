"""Unit tests for NonBlockingSemaphore in src.core.http2.semaphore."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.core.http2.semaphore import NonBlockingSemaphore


class TestNonBlockingSemaphore:
    """Tests for NonBlockingSemaphore."""

    @pytest.mark.asyncio
    async def test_acquire_nowait_success(self) -> None:
        """Non-blocking acquire_nowait returns True when slot available."""
        sem = NonBlockingSemaphore(3)
        result = sem.acquire_nowait()
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_nowait_full(self) -> None:
        """Non-blocking acquire_nowait returns False when all slots taken."""
        sem = NonBlockingSemaphore(2)
        assert sem.acquire_nowait() is True
        assert sem.acquire_nowait() is True
        assert sem.acquire_nowait() is False

    @pytest.mark.asyncio
    async def test_acquire_nowait_asyncio_backend(self) -> None:
        """acquire_nowait works with the asyncio (anyio) backend."""
        sem = NonBlockingSemaphore(1)
        # First acquire succeeds
        assert sem.acquire_nowait() is True
        # Second acquire fails (full semaphore)
        assert sem.acquire_nowait() is False

    @pytest.mark.asyncio
    async def test_acquire_nowait_trio_backend(self) -> None:
        """acquire_nowait works with the trio backend (mocked)."""
        sem = NonBlockingSemaphore(2)
        # Override the backend to simulate trio
        sem._backend = "trio"  # type: ignore[reportPrivateUsage]
        mock_trio_sem = MagicMock()
        mock_trio_sem.acquire_nowait = MagicMock()
        sem._trio_semaphore = mock_trio_sem  # type: ignore[reportPrivateUsage]

        # Create a fake trio module with WouldBlock exception
        fake_trio = MagicMock()
        fake_trio.WouldBlock = type("WouldBlock", (Exception,), {})

        # Successful acquire
        with patch.dict(sys.modules, {"trio": fake_trio}):
            result = sem.acquire_nowait()
        assert result is True
        mock_trio_sem.acquire_nowait.assert_called_once()

        # Failed acquire — simulate WouldBlock exception
        mock_trio_sem.acquire_nowait.reset_mock()
        mock_trio_sem.acquire_nowait.side_effect = fake_trio.WouldBlock("no slots")
        with patch.dict(sys.modules, {"trio": fake_trio}):
            result = sem.acquire_nowait()
        assert result is False

    @pytest.mark.asyncio
    async def test_inherits_acquire_release_unchanged(self) -> None:
        """Inherited acquire() and release() methods work unchanged."""
        sem = NonBlockingSemaphore(1)

        await sem.acquire()
        # Semaphore is now full
        assert sem.acquire_nowait() is False

        await sem.release()
        # Now we can acquire again
        assert sem.acquire_nowait() is True
