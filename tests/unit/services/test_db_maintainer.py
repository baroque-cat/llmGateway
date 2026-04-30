#!/usr/bin/env python3

"""Tests for DatabaseMaintainer — N26-N30.

Tests the conditional VACUUM ANALYZE implementation with mocked
connection pool and Prometheus metrics.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import DatabaseTableHealth
from src.services.db_maintainer import DatabaseMaintainer

# ---------------------------------------------------------------------------
# Helpers — async context-manager mocking for pool.acquire()
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def maintainer() -> DatabaseMaintainer:
    return DatabaseMaintainer()


@pytest.fixture
def db_manager() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# N26 — one table needs vacuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_one_table_needs_vacuum(
    maintainer: DatabaseMaintainer, db_manager: MagicMock
) -> None:
    """N26: 3 tables — only api_keys gets VACUUM.

    providers:  dead_ratio=0.05, n_dead_tup=50  → below threshold
    api_keys:   dead_ratio=0.5,  n_dead_tup=500 → above threshold AND > 100 rows
    key_model_status: dead_ratio=0.1, n_dead_tup=200 → below threshold

    Threshold=0.3.  Only api_keys qualifies.  Returns 1.
    """
    tables = [
        DatabaseTableHealth(
            table_name="public.providers",
            n_dead_tup=50,
            n_live_tup=950,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.05,
        ),
        DatabaseTableHealth(
            table_name="public.api_keys",
            n_dead_tup=500,
            n_live_tup=500,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.5,
        ),
        DatabaseTableHealth(
            table_name="public.key_model_status",
            n_dead_tup=200,
            n_live_tup=1800,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.1,
        ),
    ]

    conn = AsyncMock()
    pool = _make_pool_mock(conn)

    with (
        patch("src.services.db_maintainer.get_pool", return_value=pool),
        patch("src.services.db_maintainer._db_dead_tuples_gauge") as mock_tuples_gauge,
        patch("src.services.db_maintainer._db_dead_ratio_gauge") as mock_ratio_gauge,
        patch(
            "src.services.db_maintainer._db_vacuum_count_counter"
        ) as mock_vacuum_counter,
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 1

    # VACUUM only called for api_keys
    conn.execute.assert_called_once_with('VACUUM ANALYZE "public.api_keys"')

    # Vacuum counter incremented for api_keys only
    mock_vacuum_counter.labels.assert_called_with(table="public.api_keys")
    mock_vacuum_counter.labels.return_value.inc.assert_called_once()


# ---------------------------------------------------------------------------
# N27 — no tables need vacuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_no_tables_need_vacuum(
    maintainer: DatabaseMaintainer, db_manager: MagicMock
) -> None:
    """N27: All tables below threshold. No VACUUM runs. Returns 0."""
    tables = [
        DatabaseTableHealth(
            table_name="public.providers",
            n_dead_tup=10,
            n_live_tup=990,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.01,
        ),
        DatabaseTableHealth(
            table_name="public.api_keys",
            n_dead_tup=50,
            n_live_tup=950,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.05,
        ),
    ]

    conn = AsyncMock()
    pool = _make_pool_mock(conn)

    with (
        patch("src.services.db_maintainer.get_pool", return_value=pool),
        patch("src.services.db_maintainer._db_dead_tuples_gauge"),
        patch("src.services.db_maintainer._db_dead_ratio_gauge"),
        patch("src.services.db_maintainer._db_vacuum_count_counter"),
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 0
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# N28 — all tables need vacuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_all_tables_need_vacuum(
    maintainer: DatabaseMaintainer, db_manager: MagicMock
) -> None:
    """N28: All tables above threshold. All get VACUUM. Returns count."""
    tables = [
        DatabaseTableHealth(
            table_name="public.providers",
            n_dead_tup=500,
            n_live_tup=500,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.5,
        ),
        DatabaseTableHealth(
            table_name="public.api_keys",
            n_dead_tup=600,
            n_live_tup=400,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.6,
        ),
    ]

    conn = AsyncMock()
    pool = _make_pool_mock(conn)

    with (
        patch("src.services.db_maintainer.get_pool", return_value=pool),
        patch("src.services.db_maintainer._db_dead_tuples_gauge"),
        patch("src.services.db_maintainer._db_dead_ratio_gauge"),
        patch("src.services.db_maintainer._db_vacuum_count_counter"),
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 2
    assert conn.execute.call_count == 2


# ---------------------------------------------------------------------------
# N29 — Prometheus metrics updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_updates_prometheus_metrics(
    maintainer: DatabaseMaintainer, db_manager: MagicMock
) -> None:
    """N29: Vacuum runs for api_keys. Verify Prometheus gauges and counter updated."""
    tables = [
        DatabaseTableHealth(
            table_name="public.api_keys",
            n_dead_tup=500,
            n_live_tup=500,
            last_vacuum=None,
            last_analyze=None,
            dead_tuple_ratio=0.5,
        ),
    ]

    conn = AsyncMock()
    pool = _make_pool_mock(conn)

    with (
        patch("src.services.db_maintainer.get_pool", return_value=pool),
        patch("src.services.db_maintainer._db_dead_tuples_gauge") as mock_tuples_gauge,
        patch("src.services.db_maintainer._db_dead_ratio_gauge") as mock_ratio_gauge,
        patch(
            "src.services.db_maintainer._db_vacuum_count_counter"
        ) as mock_vacuum_counter,
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 1

    # Verify dead tuples gauge set
    mock_tuples_gauge.labels.assert_called_with(table="public.api_keys")
    mock_tuples_gauge.labels.return_value.set.assert_called_with(500)

    # Verify dead ratio gauge set
    mock_ratio_gauge.labels.assert_called_with(table="public.api_keys")
    mock_ratio_gauge.labels.return_value.set.assert_called_with(0.5)

    # Verify vacuum count counter incremented
    mock_vacuum_counter.labels.assert_called_with(table="public.api_keys")
    mock_vacuum_counter.labels.return_value.inc.assert_called_once()


# ---------------------------------------------------------------------------
# N30 — empty table list skips vacuum with warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_empty_table_list_skips(
    maintainer: DatabaseMaintainer, db_manager: MagicMock, caplog
) -> None:
    """N30: tables=[] → returns 0, no VACUUM, warning logged."""
    with (
        patch("src.services.db_maintainer.get_pool"),
        patch("src.services.db_maintainer._db_dead_tuples_gauge"),
        patch("src.services.db_maintainer._db_dead_ratio_gauge"),
        patch("src.services.db_maintainer._db_vacuum_count_counter"),
        caplog.at_level(logging.WARNING, logger="src.services.db_maintainer"),
    ):
        result = await maintainer.run_conditional_vacuum([], db_manager, threshold=0.3)

    assert result == 0
    assert any("No table health data" in record.message for record in caplog.records)
