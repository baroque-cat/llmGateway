#!/usr/bin/env python3

"""Tests for KeyPurger — N20-N25.

Tests the PostgreSQL-backed key purging implementation with mocked
DatabaseManager and connection pool.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.key_purger import KeyPurger

# ---------------------------------------------------------------------------
# Helpers — async context-manager mocking for pool.acquire() / conn.transaction()
# ---------------------------------------------------------------------------


def _make_async_cm(return_value):
    """Create an async context manager that yields *return_value*."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_pool_mock(conn_mock: AsyncMock) -> MagicMock:
    """Create a mock pool whose ``acquire()`` yields *conn_mock*."""
    pool = MagicMock()
    pool.acquire.return_value = _make_async_cm(conn_mock)
    return pool


def _make_conn_mock() -> MagicMock:
    """Create a mock asyncpg connection with async fetchval/execute and transaction() async CM.

    Using MagicMock for the connection so that ``transaction()`` returns
    the custom async context manager rather than an AsyncMock coroutine.
    """
    conn = MagicMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    conn.transaction.return_value = _make_async_cm(None)
    return conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def purger() -> KeyPurger:
    return KeyPurger()


@pytest.fixture
def db_manager() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# N20 — purge_provider deletes provider and returns key count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_provider_deletes_provider_and_returns_count(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N20: purge_provider(5, db_manager) — provider 5 has 10 keys.

    Mock fetchval to return 10 and execute as AsyncMock.
    Verify DELETE FROM providers WHERE id = $1 called with provider_id=5.
    Return value 10.
    """
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=10)
    conn.execute = AsyncMock()
    pool = _make_pool_mock(conn)

    with patch("src.services.key_purger.get_pool", return_value=pool):
        result = await purger.purge_provider(5, db_manager)

    assert result == 10

    # Verify fetchval called for key count
    conn.fetchval.assert_any_call(
        "SELECT COUNT(*) FROM api_keys WHERE provider_id = $1", 5
    )
    # Verify execute called for DELETE
    conn.execute.assert_called_once_with("DELETE FROM providers WHERE id = $1", 5)


# ---------------------------------------------------------------------------
# N21 — purge_provider returns 0 when provider has no keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_provider_no_keys_returns_zero(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N21: purge_provider(5, db_manager) — mock fetchval returns 0.

    Returns 0.
    """
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()
    pool = _make_pool_mock(conn)

    with patch("src.services.key_purger.get_pool", return_value=pool):
        result = await purger.purge_provider(5, db_manager)

    assert result == 0
    conn.execute.assert_called_once_with("DELETE FROM providers WHERE id = $1", 5)


# ---------------------------------------------------------------------------
# N22 — purge_stopped_keys deletes stopped keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_stopped_keys_deletes_stopped_keys(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N22: 2 stopped keys deleted, 1 valid remains.

    Mock fetchval returns 2. Verify correct query with cutoff.
    """
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=2)
    pool = _make_pool_mock(conn)
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)

    with (
        patch("src.services.key_purger.get_pool", return_value=pool),
        patch("src.services.key_purger.record_purged_keys"),
    ):
        result = await purger.purge_stopped_keys("openai", 5, cutoff, db_manager)

    assert result == 2

    # Verify fetchval called with provider_id and cutoff
    call_args = conn.fetchval.call_args
    assert call_args[0][1] == 5  # provider_id = $1
    assert call_args[0][2] == cutoff  # cutoff = $2


# ---------------------------------------------------------------------------
# N23 — purge_stopped_keys: mixed-status key NOT deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_stopped_keys_mixed_status_key_not_deleted(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N23: Key with 2 model-status rows: 1 stopped, 1 valid.

    The ``bool_and()`` in SQL ensures the key is NOT deleted.
    ``fetchval`` returns 0. Verify return 0.
    """
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=0)
    pool = _make_pool_mock(conn)
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)

    with (
        patch("src.services.key_purger.get_pool", return_value=pool),
        patch("src.services.key_purger.record_purged_keys"),
    ):
        result = await purger.purge_stopped_keys("openai", 5, cutoff, db_manager)

    assert result == 0


# ---------------------------------------------------------------------------
# N24 — purge_stopped_keys: cutoff passed correctly to SQL parameters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_stopped_keys_cutoff_calculation(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N24: Verify cutoff datetime is passed correctly as $2 parameter."""
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=1)
    pool = _make_pool_mock(conn)
    cutoff = datetime(2024, 6, 15, 12, 30, 0, tzinfo=UTC)

    with (
        patch("src.services.key_purger.get_pool", return_value=pool),
        patch("src.services.key_purger.record_purged_keys"),
    ):
        result = await purger.purge_stopped_keys("openai", 5, cutoff, db_manager)

    assert result == 1

    # Verify cutoff is the second positional argument to fetchval
    call_args = conn.fetchval.call_args
    assert call_args[0][2] == cutoff


# ---------------------------------------------------------------------------
# N25 — purge_stopped_keys: next_check_time condition in query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_stopped_keys_next_check_time_condition(
    purger: KeyPurger, db_manager: MagicMock
) -> None:
    """N25: Query includes ``next_check_time > NOW() + INTERVAL '300 days'``."""
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=0)
    pool = _make_pool_mock(conn)
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)

    with (
        patch("src.services.key_purger.get_pool", return_value=pool),
        patch("src.services.key_purger.record_purged_keys"),
    ):
        await purger.purge_stopped_keys("openai", 5, cutoff, db_manager)

    # Verify the SQL query string contains the next_check_time condition
    call_args = conn.fetchval.call_args
    query: str = call_args[0][0]
    assert "next_check_time > NOW() + INTERVAL '300 days'" in query
