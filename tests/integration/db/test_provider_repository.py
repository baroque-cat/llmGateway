"""Integration tests for ProviderRepository against a live PostgreSQL database.

Tests cover provider synchronization (add/delete in a single transaction)
and ID mapping retrieval.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from asyncpg import Pool

from src.db.database import DatabaseManager, ProviderRepository
from src.services.key_purger import KeyPurger


@pytest_asyncio.fixture
async def provider_repo(
    pg_pool: Pool, db_manager: DatabaseManager
) -> AsyncGenerator[ProviderRepository]:
    """ProviderRepository with KeyPurger patched to use test pool.

    Patches ``src.services.key_purger.get_pool`` to return the test pool,
    ensuring ``KeyPurger.purge_provider()`` uses the same connection pool
    as the rest of the test.
    """
    import src.services.key_purger as kp_module

    original = kp_module.get_pool
    kp_module.get_pool = lambda: pg_pool
    try:
        key_purger = KeyPurger()
        yield ProviderRepository(pg_pool, key_purger)
    finally:
        kp_module.get_pool = original


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_inserts_new_providers(
    pg_pool: Pool, provider_repo: ProviderRepository, db_manager: DatabaseManager
) -> None:
    """sync() inserts new providers into an empty database."""
    await provider_repo.sync(["p1", "p2"], db_manager)
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM providers ORDER BY name")
    names = [row["name"] for row in rows]
    assert names == ["p1", "p2"]


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_deletes_removed_providers(
    pg_pool: Pool, provider_repo: ProviderRepository, db_manager: DatabaseManager
) -> None:
    """sync() deletes obsolete providers and cascades to api_keys."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('old_prov')")
        await conn.execute(
            "INSERT INTO api_keys (provider_id, key_value) "
            "SELECT id, 'sk-old' FROM providers WHERE name = 'old_prov'"
        )
    await provider_repo.sync(["new_prov"], db_manager)
    async with pg_pool.acquire() as conn:
        prov_exists = await conn.fetchval(
            "SELECT 1 FROM providers WHERE name = 'old_prov'"
        )
        key_exists = await conn.fetchval(
            "SELECT 1 FROM api_keys WHERE key_value = 'sk-old'"
        )
    assert prov_exists is None
    assert key_exists is None


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_add_and_delete_in_single_transaction(
    pg_pool: Pool, provider_repo: ProviderRepository, db_manager: DatabaseManager
) -> None:
    """sync() adds new and deletes obsolete providers atomically."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('old')")
    await provider_repo.sync(["new"], db_manager)
    async with pg_pool.acquire() as conn:
        new_exists = await conn.fetchval("SELECT 1 FROM providers WHERE name = 'new'")
        old_exists = await conn.fetchval("SELECT 1 FROM providers WHERE name = 'old'")
    assert new_exists is not None
    assert old_exists is None


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_id_map_returns_correct_mapping(
    pg_pool: Pool, provider_repo: ProviderRepository, db_manager: DatabaseManager
) -> None:
    """get_id_map() returns {name: id} for all providers."""
    await provider_repo.sync(["a", "b"], db_manager)
    id_map = await provider_repo.get_id_map()
    assert set(id_map) == {"a", "b"}
    assert isinstance(id_map["a"], int)
    assert isinstance(id_map["b"], int)
    assert id_map["a"] > 0
    assert id_map["b"] > 0
