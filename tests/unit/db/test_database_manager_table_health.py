#!/usr/bin/env python3

"""Unit tests for DatabaseManager.get_table_health() — tests N49-N51.

Verifies that get_table_health() queries pg_stat_user_tables, returns
list[DatabaseTableHealth] with correct field values, and handles empty
databases gracefully.

Also includes regression guard tests (N53) verifying that run_vacuum
has been removed from DatabaseManager.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import DatabaseTableHealth
from src.db.database import DatabaseManager


def _make_mock_pool_and_conn(
    fetch_return: list[dict] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build a mock pool and connection for DatabaseManager tests.

    Returns (mock_pool, mock_conn).
    """
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    if fetch_return is None:
        fetch_return = [
            {
                "table_name": "public.api_keys",
                "n_dead_tup": 500,
                "n_live_tup": 1000,
                "last_vacuum": None,
                "last_analyze": None,
                "dead_tuple_ratio": 0.33,
            }
        ]

    mock_conn.fetch = AsyncMock(return_value=fetch_return)

    # pool.acquire() returns async context manager → conn
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    return mock_pool, mock_conn


@pytest.mark.asyncio
async def test_get_table_health_returns_list_of_database_table_health():
    """N49: get_table_health() returns list[DatabaseTableHealth] with correct fields."""
    mock_pool, mock_conn = _make_mock_pool_and_conn()
    mock_accessor = MagicMock()

    with patch("src.db.database.get_pool", return_value=mock_pool):
        db_manager = DatabaseManager(mock_accessor)
        result = await db_manager.get_table_health()

    assert isinstance(result, list)
    assert len(result) == 1
    item = result[0]
    assert isinstance(item, DatabaseTableHealth)
    assert item.table_name == "public.api_keys"
    assert item.n_dead_tup == 500
    assert item.n_live_tup == 1000
    assert item.last_vacuum is None
    assert item.last_analyze is None
    assert item.dead_tuple_ratio == 0.33


@pytest.mark.asyncio
async def test_get_table_health_empty_database_returns_empty_list():
    """N50: Empty database returns empty list (not error)."""
    mock_pool, mock_conn = _make_mock_pool_and_conn(fetch_return=[])
    mock_accessor = MagicMock()

    with patch("src.db.database.get_pool", return_value=mock_pool):
        db_manager = DatabaseManager(mock_accessor)
        result = await db_manager.get_table_health()

    assert result == []


@pytest.mark.asyncio
async def test_get_table_health_queries_pg_stat_user_tables():
    """N51: The SQL query contains 'pg_stat_user_tables' and 'public'."""
    mock_pool, mock_conn = _make_mock_pool_and_conn()
    mock_accessor = MagicMock()

    with patch("src.db.database.get_pool", return_value=mock_pool):
        db_manager = DatabaseManager(mock_accessor)
        await db_manager.get_table_health()

    # Verify the query passed to conn.fetch contains expected fragments
    call_args = mock_conn.fetch.call_args
    query = call_args[0][0]
    assert "pg_stat_user_tables" in query
    assert "public" in query


# --- Regression guard: run_vacuum removed, get_table_health present ---


def test_database_manager_run_vacuum_removed():
    """N53: DatabaseManager no longer has a run_vacuum method."""
    assert hasattr(DatabaseManager, "run_vacuum") is False


def test_database_manager_has_get_table_health():
    """Verify that DatabaseManager still has get_table_health method."""
    assert hasattr(DatabaseManager, "get_table_health") is True
