#!/usr/bin/env python3

"""
Unit tests for DatabaseManager.wait_for_schema_ready() method.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asyncpg import UndefinedTableError

from src.db.database import DatabaseManager


@pytest.mark.asyncio
async def test_wait_for_schema_ready_success():
    """
    Test that wait_for_schema_ready returns immediately when the table exists.
    """
    mock_accessor = MagicMock()
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    # Simulate successful query
    mock_conn.fetchval = AsyncMock(return_value=1)

    with patch("src.db.database.get_pool", return_value=mock_pool):
        manager = DatabaseManager(mock_accessor)
        # Should not raise
        await manager.wait_for_schema_ready(timeout=1)

    # Verify the query was called
    mock_conn.fetchval.assert_called_once_with("SELECT 1 FROM key_model_status LIMIT 1")


@pytest.mark.asyncio
async def test_wait_for_schema_ready_retries_on_undefined_table_error():
    """
    Test that wait_for_schema_ready retries when UndefinedTableError is raised,
    and eventually succeeds.
    """
    mock_accessor = MagicMock()
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # First call raises UndefinedTableError, second call succeeds
    mock_conn.fetchval = AsyncMock(
        side_effect=[
            UndefinedTableError('relation "key_model_status" does not exist'),
            1,
        ]
    )

    with patch("src.db.database.get_pool", return_value=mock_pool):
        manager = DatabaseManager(mock_accessor)
        # Should not raise, should retry
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await manager.wait_for_schema_ready(timeout=10)
            # Should have slept once
            mock_sleep.assert_called_once_with(2)

    # fetchval called twice
    assert mock_conn.fetchval.call_count == 2


@pytest.mark.asyncio
async def test_wait_for_schema_ready_timeout():
    """
    Test that wait_for_schema_ready raises TimeoutError after the specified timeout.
    """
    mock_accessor = MagicMock()
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Always raise UndefinedTableError
    mock_conn.fetchval = AsyncMock(
        side_effect=UndefinedTableError("relation does not exist")
    )

    with patch("src.db.database.get_pool", return_value=mock_pool):
        manager = DatabaseManager(mock_accessor)
        # Should raise TimeoutError
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Use a short timeout to speed up test
            with pytest.raises(
                TimeoutError, match="Database schema not ready after 0.1 seconds."
            ):
                await manager.wait_for_schema_ready(timeout=0.1)
            # Should have slept a few times (but timeout short, may not sleep)
            # We'll just ensure sleep was called at least once (since retry interval is 2 seconds,
            # but timeout is 0.1 seconds, may not sleep). Let's not assert.


@pytest.mark.asyncio
async def test_wait_for_schema_ready_other_exception_retries():
    """
    Test that wait_for_schema_ready retries on other exceptions (e.g., connection errors)
    and eventually succeeds.
    """
    mock_accessor = MagicMock()
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # First call raises generic Exception, second call succeeds
    mock_conn.fetchval = AsyncMock(side_effect=[Exception("Some temporary error"), 1])

    with patch("src.db.database.get_pool", return_value=mock_pool):
        manager = DatabaseManager(mock_accessor)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await manager.wait_for_schema_ready(timeout=10)
            mock_sleep.assert_called_once_with(2)

    assert mock_conn.fetchval.call_count == 2


@pytest.mark.asyncio
async def test_wait_for_schema_ready_logging():
    """
    Test that appropriate log messages are emitted.
    """
    mock_accessor = MagicMock()
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetchval = AsyncMock(return_value=1)

    with patch("src.db.database.get_pool", return_value=mock_pool):
        manager = DatabaseManager(mock_accessor)
        with patch("src.db.database.logger") as mock_logger:
            await manager.wait_for_schema_ready(timeout=1)
            # Should log info when schema is ready
            mock_logger.info.assert_called_with("Database schema is ready.")


if __name__ == "__main__":
    asyncio.run(test_wait_for_schema_ready_success())
