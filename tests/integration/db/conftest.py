"""Shared fixtures for PostgreSQL integration tests.

Provides connection pooling and schema management against the
test-database Docker service (port 5433).

Fixtures:
    pg_pool          — session-scoped asyncpg pool, fast-fail if unreachable
    _ensure_schema   — autouse: CREATE TABLE IF NOT EXISTS before test,
                       TRUNCATE ... CASCADE after (FK-safe order)
    db_manager       — function-scoped DatabaseManager patched to use test pool
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from asyncpg import Pool

from src.db.database import DB_SCHEMA, DatabaseManager

# ── DSN for test-database (port 5433, test credentials) ──
# boundary: test-database credentials match docker-compose.yml:85-89
TEST_DSN = "postgresql://test_user:test_password@localhost:5433/test_db"

# ── Table list for teardown (child-first for FK CASCADE safety) ──
_TEARDOWN_ORDER = (
    "key_model_status",
    "provider_proxy_status",
    "api_keys",
    "proxies",
    "providers",
)


@pytest_asyncio.fixture(scope="session")
async def pg_pool() -> AsyncGenerator[Pool]:
    """Session-scoped asyncpg pool connected to test-database.

    Fast-fail check: runs ``SELECT 1`` to verify connectivity.
    Skips entire test session if database is unreachable.
    """
    try:
        pool = await asyncpg.create_pool(
            dsn=TEST_DSN,
            min_size=1,
            max_size=5,
            command_timeout=30.0,
        )
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception:
        pytest.skip("PostgreSQL test-database not available (port 5433)")
        # Never reached due to skip, but pyright needs the path
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]
        return

    yield pool
    await pool.close()


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema(pg_pool: Pool) -> AsyncGenerator[None]:
    """Create schema before each test, truncate after.

    Schema creation is idempotent (``CREATE TABLE IF NOT EXISTS``).
    Teardown uses ``TRUNCATE ... CASCADE`` in FK-safe order.
    """
    async with pg_pool.acquire() as conn:
        await conn.execute(DB_SCHEMA)
    yield
    async with pg_pool.acquire() as conn:
        for table in _TEARDOWN_ORDER:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")


@pytest_asyncio.fixture
async def db_manager(pg_pool: Pool) -> DatabaseManager:
    """Create a DatabaseManager connected to the test pool.

    Patches ``get_pool()`` to return the test pool instead of
    the module-level production singleton.
    """
    import src.db.database as db_module

    original_get_pool = db_module.get_pool
    db_module.get_pool = lambda: pg_pool  # type: ignore[assignment]
    try:
        manager = DatabaseManager()
        yield manager
    finally:
        db_module.get_pool = original_get_pool  # type: ignore[assignment]
