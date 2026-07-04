"""Smoke tests for the Block 2 database fixtures.

Verifies that the session-scoped ``pg_pool`` connects to the test-database
and that the ``db_manager`` fixture provides a working DatabaseManager.
"""

from __future__ import annotations

import pytest
from asyncpg import Pool

from src.db.database import DatabaseManager


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_pg_pool_connects(pg_pool: Pool) -> None:
    """pg_pool is connected and can execute SQL."""
    async with pg_pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_db_manager_creates_schema(db_manager: DatabaseManager) -> None:
    """DatabaseManager can initialize schema without errors."""
    await db_manager.initialize_schema()


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_db_manager_check_connection(db_manager: DatabaseManager) -> None:
    """DatabaseManager.check_connection returns True."""
    assert await db_manager.check_connection() is True
