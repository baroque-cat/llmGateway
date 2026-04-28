#!/usr/bin/env python3

"""
Unit tests for init_db_pool parameterization.

Tests cover the min_size / max_size defaults, custom overrides,
and the singleton guard that prevents re-initialization.

Test IDs: UT-DB01, UT-DB02, UT-DB03.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db import database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_pool():
    """Reset the module-level _db_pool to None before and after each test."""
    database._db_pool = None
    yield
    database._db_pool = None


# ---------------------------------------------------------------------------
# UT-DB01: Default parameters → create_pool called with min_size=1, max_size=15
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_pool_default_params():
    """UT-DB01: init_db_pool(dsn) without min/max → asyncpg.create_pool called
    with min_size=1, max_size=15."""
    mock_pool = MagicMock()

    with patch(
        "asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
    ) as mock_create_pool:
        await database.init_db_pool("postgresql://user:pass@localhost:5432/testdb")

    mock_create_pool.assert_called_once_with(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        min_size=1,
        max_size=15,
    )


# ---------------------------------------------------------------------------
# UT-DB02: Custom parameters → create_pool called with min_size=2, max_size=10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_pool_custom_params():
    """UT-DB02: init_db_pool(dsn, min_size=2, max_size=10) → asyncpg.create_pool
    called with those exact values."""
    mock_pool = MagicMock()

    with patch(
        "asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
    ) as mock_create_pool:
        await database.init_db_pool(
            "postgresql://user:pass@localhost:5432/testdb",
            min_size=2,
            max_size=10,
        )

    mock_create_pool.assert_called_once_with(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        min_size=2,
        max_size=10,
    )


# ---------------------------------------------------------------------------
# UT-DB03: Second call logs warning, create_pool called only once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_pool_second_call_logs_warning():
    """UT-DB03: After first init_db_pool call, a second call with different
    min/max → logs warning, asyncpg.create_pool called only once."""
    mock_pool = MagicMock()

    with patch(
        "asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
    ) as mock_create_pool:
        # First call — should succeed and create the pool.
        await database.init_db_pool(
            "postgresql://user:pass@localhost:5432/testdb",
            min_size=1,
            max_size=15,
        )

        # Second call with different parameters — should log warning and skip.
        with patch("src.db.database.logger") as mock_logger:
            await database.init_db_pool(
                "postgresql://user:pass@localhost:5432/testdb",
                min_size=2,
                max_size=10,
            )
            mock_logger.warning.assert_called_once_with(
                "Database pool already initialized."
            )

        # create_pool should have been called exactly once (from the first call).
        mock_create_pool.assert_called_once_with(
            dsn="postgresql://user:pass@localhost:5432/testdb",
            min_size=1,
            max_size=15,
        )
