"""Integration tests for the PostgreSQL schema DDL in ``DB_SCHEMA``.

Validates that ``DB_SCHEMA`` creates the expected tables, indexes, unique
constraints, and ``ON DELETE CASCADE`` foreign-key relationships against the
live test-database service (port 5433).
"""

from __future__ import annotations

import pytest
from asyncpg import Pool, UniqueViolationError

from src.db.database import DB_SCHEMA

# Names of the six performance indexes declared in ``DB_SCHEMA``.
_EXPECTED_INDEXES: frozenset[str] = frozenset(
    {
        "idx_api_keys_provider_id",
        "idx_key_model_status_status",
        "idx_proxy_status_next_check_time",
        "idx_proxy_status_status",
        "idx_key_status_next_check_time",
        "idx_key_status_gateway_lookup",
    }
)

# Names of the five tables declared in ``DB_SCHEMA``.
_EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "providers",
        "proxies",
        "provider_proxy_status",
        "api_keys",
        "key_model_status",
    }
)


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_schema_creates_all_five_tables(pg_pool: Pool) -> None:
    """``DB_SCHEMA`` creates exactly the five expected tables in ``public``."""
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
    tables = {row["tablename"] for row in rows}
    assert tables == _EXPECTED_TABLES


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_schema_idempotent_second_run(pg_pool: Pool) -> None:
    """Running ``DB_SCHEMA`` a second time raises no exception.

    Reaching the final assertion proves the second ``execute`` succeeded.
    """
    async with pg_pool.acquire() as conn:
        await conn.execute(DB_SCHEMA)
        alive = await conn.fetchval("SELECT 1")
    assert alive == 1


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_schema_idempotent_preserves_data(pg_pool: Pool) -> None:
    """A second ``DB_SCHEMA`` run preserves rows inserted before it."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_persist')")
        await conn.execute(DB_SCHEMA)
        count = await conn.fetchval("SELECT COUNT(*) FROM providers")
    assert count == 1


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_all_six_indexes_created(pg_pool: Pool) -> None:
    """All six performance indexes declared in ``DB_SCHEMA`` exist."""
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        )
    indexes = {row["indexname"] for row in rows}
    assert _EXPECTED_INDEXES.issubset(indexes)


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_foreign_key_cascade_provider_to_keys(pg_pool: Pool) -> None:
    """Deleting a provider cascades to ``api_keys`` and ``key_model_status``.

    Args:
        pg_pool: Session-scoped asyncpg pool connected to the test-database.
    """
    async with pg_pool.acquire() as conn:
        provider_id = await conn.fetchval(
            "INSERT INTO providers (name) VALUES ('cascade_provider') RETURNING id"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-cascade') RETURNING id",
            provider_id,
        )
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, next_check_time) "
            "VALUES ($1, '__ALL_MODELS__', 'untested', NOW())",
            key_id,
        )
        await conn.execute("DELETE FROM providers WHERE id = $1", provider_id)
        keys_count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE provider_id = $1", provider_id
        )
        status_count = await conn.fetchval(
            "SELECT COUNT(*) FROM key_model_status WHERE key_id = $1", key_id
        )
    assert keys_count == 0
    assert status_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_unique_constraint_provider_name(pg_pool: Pool) -> None:
    """The ``providers.name`` UNIQUE constraint rejects duplicate names."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test')")
        with pytest.raises(UniqueViolationError):
            await conn.execute("INSERT INTO providers (name) VALUES ('test')")


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_unique_constraint_provider_id_key_value(pg_pool: Pool) -> None:
    """The ``api_keys(provider_id, key_value)`` UNIQUE constraint rejects dupes.

    Args:
        pg_pool: Session-scoped asyncpg pool connected to the test-database.
    """
    async with pg_pool.acquire() as conn:
        provider_id = await conn.fetchval(
            "INSERT INTO providers (name) VALUES ('uniq_key_provider') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO api_keys (provider_id, key_value) VALUES ($1, 'sk-dup')",
            provider_id,
        )
        with pytest.raises(UniqueViolationError):
            await conn.execute(
                "INSERT INTO api_keys (provider_id, key_value) "
                "VALUES ($1, 'sk-dup')",
                provider_id,
            )
