"""Integration tests for KeyRepository against a live PostgreSQL database.

Tests cover key synchronization, status updates (failing_since logic,
ALL_MODELS_MARKER substitution), and query methods (time-filtered checks,
random key selection, valid-key caching).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from asyncpg import Pool

from src.core.constants import ALL_MODELS_MARKER, ErrorReason
from src.core.models import CheckResult
from src.db.database import KeyRepository


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_inserts_new_keys(pg_pool: Pool) -> None:
    """sync() inserts new keys and creates ALL_MODELS status rows."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
    repo = KeyRepository(pg_pool)
    await repo.sync("test_prov", provider_id, {"sk-a", "sk-b"})
    async with pg_pool.acquire() as conn:
        key_count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE provider_id = $1",
            provider_id,
        )
        kms_rows = await conn.fetch(
            "SELECT model_name, status FROM key_model_status "
            "WHERE key_id IN (SELECT id FROM api_keys WHERE provider_id = $1)",
            provider_id,
        )
    assert key_count == 2
    assert len(kms_rows) == 2
    for row in kms_rows:
        assert row["model_name"] == ALL_MODELS_MARKER
        assert row["status"] == "untested"


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_no_duplicate_keys_on_rerun(pg_pool: Pool) -> None:
    """sync() is idempotent — running twice does not duplicate keys."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
    repo = KeyRepository(pg_pool)
    await repo.sync("test_prov", provider_id, {"sk-a"})
    await repo.sync("test_prov", provider_id, {"sk-a"})
    async with pg_pool.acquire() as conn:
        key_count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys "
            "WHERE provider_id = $1 AND key_value = 'sk-a'",
            provider_id,
        )
    assert key_count == 1


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_all_models_marker_association(pg_pool: Pool) -> None:
    """sync() creates key_model_status rows exclusively with ALL_MODELS_MARKER.

    Verifies that every ``key_model_status`` row produced by ``sync()``
    uses ``model_name = '__ALL_MODELS__'``, regardless of how many keys
    are inserted.
    """
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
    repo = KeyRepository(pg_pool)
    await repo.sync("test_prov", provider_id, {"sk-1", "sk-2", "sk-3"})
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT model_name, status FROM key_model_status "
            "WHERE key_id IN (SELECT id FROM api_keys WHERE provider_id = $1)",
            provider_id,
        )
    assert len(rows) == 3
    for row in rows:
        assert row["model_name"] == ALL_MODELS_MARKER
        assert row["status"] == "untested"


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_sync_removes_stale_model_associations(pg_pool: Pool) -> None:
    """sync() removes key_model_status rows not matching ALL_MODELS_MARKER."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-test') RETURNING id",
            provider_id,
        )
        now = datetime.now(UTC)
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, failing_since, next_check_time) "
            "VALUES ($1, $2, 'untested', NULL, $3)",
            key_id,
            ALL_MODELS_MARKER,
            now,
        )
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, failing_since, next_check_time) "
            "VALUES ($1, 'test-model', 'untested', NULL, $2)",
            key_id,
            now,
        )
    repo = KeyRepository(pg_pool)
    await repo.sync("test_prov", provider_id, {"sk-test"})
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT model_name FROM key_model_status WHERE key_id = $1",
            key_id,
        )
    assert len(rows) == 1
    assert rows[0]["model_name"] == ALL_MODELS_MARKER


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_update_status_failing_since_logic(pg_pool: Pool) -> None:
    """update_status() preserves failing_since across failures and clears it on success."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-test') RETURNING id",
            provider_id,
        )
        now = datetime.now(UTC)
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, failing_since, next_check_time) "
            "VALUES ($1, $2, 'untested', NULL, $3)",
            key_id,
            ALL_MODELS_MARKER,
            now,
        )
    repo = KeyRepository(pg_pool)
    next_check = datetime.now(UTC) + timedelta(minutes=5)

    # Phase 1: first failure sets failing_since.
    await repo.update_status(
        key_id,
        ALL_MODELS_MARKER,
        "test_prov",
        CheckResult.fail(ErrorReason.RATE_LIMITED),
        next_check,
    )
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, failing_since FROM key_model_status "
            "WHERE key_id = $1 AND model_name = $2",
            key_id,
            ALL_MODELS_MARKER,
        )
    assert row is not None
    assert row["status"] == "rate_limited"
    assert row["failing_since"] is not None
    first_failing = row["failing_since"]

    # Phase 2: second failure preserves failing_since (COALESCE).
    await repo.update_status(
        key_id,
        ALL_MODELS_MARKER,
        "test_prov",
        CheckResult.fail(ErrorReason.SERVER_ERROR),
        next_check,
    )
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, failing_since FROM key_model_status "
            "WHERE key_id = $1 AND model_name = $2",
            key_id,
            ALL_MODELS_MARKER,
        )
    assert row is not None
    assert row["status"] == "server_error"
    assert row["failing_since"] == first_failing

    # Phase 3: success clears failing_since to NULL.
    await repo.update_status(
        key_id,
        ALL_MODELS_MARKER,
        "test_prov",
        CheckResult.success(),
        next_check,
    )
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, failing_since FROM key_model_status "
            "WHERE key_id = $1 AND model_name = $2",
            key_id,
            ALL_MODELS_MARKER,
        )
    assert row is not None
    assert row["status"] == "valid"
    assert row["failing_since"] is None


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_update_status_all_models_marker_substitution(pg_pool: Pool) -> None:
    """update_status() always writes to the ALL_MODELS_MARKER row."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-test') RETURNING id",
            provider_id,
        )
        now = datetime.now(UTC)
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, failing_since, next_check_time) "
            "VALUES ($1, $2, 'untested', NULL, $3)",
            key_id,
            ALL_MODELS_MARKER,
            now,
        )
    repo = KeyRepository(pg_pool)
    next_check = datetime.now(UTC) + timedelta(minutes=5)
    await repo.update_status(
        key_id,
        "test-model",
        "test_prov",
        CheckResult.success(),
        next_check,
    )
    async with pg_pool.acquire() as conn:
        all_models_row = await conn.fetchrow(
            "SELECT status FROM key_model_status "
            "WHERE key_id = $1 AND model_name = $2",
            key_id,
            ALL_MODELS_MARKER,
        )
        test_model_exists = await conn.fetchval(
            "SELECT 1 FROM key_model_status "
            "WHERE key_id = $1 AND model_name = 'test-model'",
            key_id,
        )
    assert all_models_row is not None
    assert all_models_row["status"] == "valid"
    assert test_model_exists is None


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_keys_to_check_time_filter(pg_pool: Pool) -> None:
    """get_keys_to_check() only returns keys with next_check_time <= NOW()."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key1_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-overdue') RETURNING id",
            provider_id,
        )
        key2_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-future') RETURNING id",
            provider_id,
        )
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, next_check_time) "
            "VALUES ($1, $2, 'untested', NOW() - INTERVAL '1 hour')",
            key1_id,
            ALL_MODELS_MARKER,
        )
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, next_check_time) "
            "VALUES ($1, $2, 'untested', NOW() + INTERVAL '1 hour')",
            key2_id,
            ALL_MODELS_MARKER,
        )
    repo = KeyRepository(pg_pool)
    result = await repo.get_keys_to_check(["test_prov"])
    assert len(result) == 1
    assert result[0]["key_id"] == key1_id


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_available_key_random_selection(pg_pool: Pool) -> None:
    """get_available_key() returns random keys from the valid pool."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        for i in range(5):
            key_id = await conn.fetchval(
                "INSERT INTO api_keys (provider_id, key_value) "
                "VALUES ($1, $2) RETURNING id",
                provider_id,
                f"sk-{i}",
            )
            await conn.execute(
                "INSERT INTO key_model_status "
                "(key_id, model_name, status, next_check_time) "
                "VALUES ($1, $2, 'valid', NOW())",
                key_id,
                ALL_MODELS_MARKER,
            )
    repo = KeyRepository(pg_pool)
    key_ids: set[int] = set()
    for _ in range(10):
        result = await repo.get_available_key("test_prov", "any-model")
        assert result is not None
        key_ids.add(result["key_id"])
    assert len(key_ids) >= 2


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_valid_keys_for_caching_includes_untested(
    pg_pool: Pool,
) -> None:
    """get_all_valid_keys_for_caching() includes keys with no status row."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-test') RETURNING id",
            provider_id,
        )
    repo = KeyRepository(pg_pool)
    result = await repo.get_all_valid_keys_for_caching()
    key_ids = {r["key_id"] for r in result}
    assert key_id in key_ids


@pytest.mark.postgres
@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_valid_keys_for_caching_excludes_fatal_status(
    pg_pool: Pool,
) -> None:
    """get_all_valid_keys_for_caching() excludes keys with fatal statuses."""
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO providers (name) VALUES ('test_prov')")
        provider_id = await conn.fetchval(
            "SELECT id FROM providers WHERE name = 'test_prov'"
        )
        key_id = await conn.fetchval(
            "INSERT INTO api_keys (provider_id, key_value) "
            "VALUES ($1, 'sk-test') RETURNING id",
            provider_id,
        )
        await conn.execute(
            "INSERT INTO key_model_status "
            "(key_id, model_name, status, next_check_time) "
            "VALUES ($1, $2, 'invalid_key', NOW())",
            key_id,
            ALL_MODELS_MARKER,
        )
    repo = KeyRepository(pg_pool)
    result = await repo.get_all_valid_keys_for_caching()
    key_ids = {r["key_id"] for r in result}
    assert key_id not in key_ids
