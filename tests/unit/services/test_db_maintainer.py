#!/usr/bin/env python3

"""Tests for DatabaseMaintainer — N26-N30.

Tests the conditional VACUUM ANALYZE implementation with mocked
connection pool and metrics collector.  The module-level globals
(_db_dead_tuples_gauge, etc.) have been replaced by the
collector-based approach, so we mock ``_db_maintainer_collector``
to return a ``MemoryMetricsCollector``.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import DatabaseTableHealth
from src.metrics.backends.memory import MemoryMetricsCollector
from src.services.db_maintainer import DatabaseMaintainer


# ---------------------------------------------------------------------------
# Helpers — async context-manager mocking for pool.acquire()
# ---------------------------------------------------------------------------


def _make_async_cm(return_value: AsyncMock) -> MagicMock:
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


@pytest.fixture
def memory_collector() -> MemoryMetricsCollector:
    """Provide a fresh MemoryMetricsCollector for each test."""
    return MemoryMetricsCollector()


# ---------------------------------------------------------------------------
# N26 — one table needs vacuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_one_table_needs_vacuum(
    maintainer: DatabaseMaintainer, db_manager: MagicMock, memory_collector: MemoryMetricsCollector
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
        patch(
            "src.services.db_maintainer._db_maintainer_collector",
            return_value=memory_collector,
        ),
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 1

    # VACUUM only called for api_keys
    conn.execute.assert_called_once_with('VACUUM ANALYZE "public.api_keys"')

    # Verify metrics were recorded in the memory collector
    body, _ = memory_collector.generate_metrics()
    # Dead tuples gauge should have been set for all 3 tables
    assert "public.providers" in body
    assert "public.api_keys" in body
    assert "public.key_model_status" in body


# ---------------------------------------------------------------------------
# N27 — no tables need vacuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_no_tables_need_vacuum(
    maintainer: DatabaseMaintainer, db_manager: MagicMock, memory_collector: MemoryMetricsCollector
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
        patch(
            "src.services.db_maintainer._db_maintainer_collector",
            return_value=memory_collector,
        ),
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
    maintainer: DatabaseMaintainer, db_manager: MagicMock, memory_collector: MemoryMetricsCollector
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
        patch(
            "src.services.db_maintainer._db_maintainer_collector",
            return_value=memory_collector,
        ),
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
    maintainer: DatabaseMaintainer, db_manager: MagicMock, memory_collector: MemoryMetricsCollector
) -> None:
    """N29: Vacuum runs for api_keys. Verify metrics gauges and counter updated."""
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
        patch(
            "src.services.db_maintainer._db_maintainer_collector",
            return_value=memory_collector,
        ),
    ):
        result = await maintainer.run_conditional_vacuum(
            tables, db_manager, threshold=0.3
        )

    assert result == 1

    # Verify dead tuples gauge was set
    body, _ = memory_collector.generate_metrics()
    assert "500.0" in body
    assert "public.api_keys" in body

    # Verify dead ratio gauge was set (0.5)
    assert "0.5" in body

    # Verify vacuum counter was incremented (1.0)
    assert "1.0" in body


# ---------------------------------------------------------------------------
# N30 — empty table list skips vacuum with warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conditional_vacuum_empty_table_list_skips(
    maintainer: DatabaseMaintainer, db_manager: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """N30: tables=[] → returns 0, no VACUUM, warning logged."""
    with (
        patch("src.services.db_maintainer.get_pool"),
        patch(
            "src.services.db_maintainer._db_maintainer_collector",
            return_value=MemoryMetricsCollector(),
        ),
        caplog.at_level(logging.WARNING, logger="src.services.db_maintainer"),
    ):
        result = await maintainer.run_conditional_vacuum([], db_manager, threshold=0.3)

    assert result == 0
    assert any("No table health data" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# record_purged_keys — module-level function
# ---------------------------------------------------------------------------


def test_record_purged_keys_updates_counter(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """Verify record_purged_keys() increments the DB_PURGED_KEYS counter."""
    with patch(
        "src.services.db_maintainer._db_maintainer_collector",
        return_value=memory_collector,
    ):
        from src.services.db_maintainer import record_purged_keys

        record_purged_keys("openai", 5)

    body, _ = memory_collector.generate_metrics()
    assert "openai" in body
    assert "5.0" in body


def test_record_purged_keys_zero_count_no_op(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """Verify record_purged_keys() with count=0 does not create a counter."""
    with patch(
        "src.services.db_maintainer._db_maintainer_collector",
        return_value=memory_collector,
    ):
        from src.services.db_maintainer import record_purged_keys

        record_purged_keys("openai", 0)

    # No metrics should have been recorded
    body, _ = memory_collector.generate_metrics()
    # The body should only contain the empty metrics structure
    assert "openai" not in body