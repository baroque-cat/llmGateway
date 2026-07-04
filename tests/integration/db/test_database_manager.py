"""Integration tests for the :class:`DatabaseManager` facade.

Validates schema initialization, connection checking, schema-readiness
waiting, and table-health reporting against the test-database service
on port 5433.
"""

from __future__ import annotations

import pytest
from asyncpg import Pool

import src.db.database as db_module
from src.core.models import DatabaseTableHealth
from src.db.database import DatabaseManager


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_initialize_schema_creates_all_tables(
    db_manager: DatabaseManager,
) -> None:
    """Verify ``initialize_schema`` is idempotent and creates all five tables.

    The autouse ``_ensure_schema`` fixture already created the schema, but
    ``initialize_schema`` uses ``CREATE TABLE IF NOT EXISTS`` so re-running
    it must succeed without error and leave all five tables present in the
    ``public`` schema.
    """
    await db_manager.initialize_schema()

    pool = db_module.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
    actual_tables = {row["tablename"] for row in rows}
    assert actual_tables == {
        "providers",
        "proxies",
        "provider_proxy_status",
        "api_keys",
        "key_model_status",
    }


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_check_connection_returns_true(db_manager: DatabaseManager) -> None:
    """Verify ``check_connection`` returns ``True`` when the database is up."""
    result = await db_manager.check_connection()
    assert result is True


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_wait_for_schema_ready_returns_immediately(
    db_manager: DatabaseManager,
) -> None:
    """Verify ``wait_for_schema_ready`` returns without raising.

    The ``_ensure_schema`` fixture already created ``key_model_status``, so
    the method must return immediately rather than raise ``TimeoutError``.
    """
    await db_manager.wait_for_schema_ready(timeout=5)


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_table_health_returns_all_tables(
    db_manager: DatabaseManager,
) -> None:
    """Verify ``get_table_health`` returns one record per public-schema table."""
    health: list[DatabaseTableHealth] = await db_manager.get_table_health()
    assert len(health) == 5
    actual_names = {entry.table_name for entry in health}
    assert actual_names == {
        "public.providers",
        "public.proxies",
        "public.provider_proxy_status",
        "public.api_keys",
        "public.key_model_status",
    }


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_table_health_dead_tuple_ratio(
    pg_pool: Pool, db_manager: DatabaseManager
) -> None:
    """Verify ``get_table_health`` reports non-negative counts after churn.

    Inserts and deletes a row in ``providers`` to generate dead tuples, then
    verifies the ``public.providers`` health record has sane non-negative
    values. Autovacuum may already reclaim dead tuples, so only the
    non-negativity invariant is asserted.
    """
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('temp')")
        await conn.execute("DELETE FROM providers WHERE name = 'temp'")

    health = await db_manager.get_table_health()
    providers_health: DatabaseTableHealth = next(
        entry for entry in health if entry.table_name == "public.providers"
    )
    assert providers_health.n_dead_tup >= 0
    assert providers_health.n_live_tup >= 0
    assert providers_health.dead_tuple_ratio >= 0.0
