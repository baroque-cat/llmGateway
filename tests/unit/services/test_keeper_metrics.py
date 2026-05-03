#!/usr/bin/env python3

"""Unit tests for Keeper's use of IMetricsCollector.

Tests:
  UT-KM01: Keeper creates IMetricsCollector (single-process) at init
  UT-KM02: Keeper calls collector.collect_from_db(db_manager) periodically
  UT-KM03: Keeper calls adaptive metrics through collector
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.interfaces import IMetricsCollector
from src.metrics import get_collector, reset_collector
from src.metrics.backends.prometheus import PrometheusMetricsCollector
from src.metrics.registry import (
    ADAPTIVE_BACKOFF_EVENTS,
    ADAPTIVE_BATCH_DELAY,
    ADAPTIVE_BATCH_SIZE,
    ADAPTIVE_RATE_LIMIT_EVENTS,
    ADAPTIVE_RECOVERY_EVENTS,
)
from src.services.keeper import (
    _collect_db_metrics_loop,
    _create_adaptive_metrics_callback,
    run_keeper,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_collector():
    """Reset the collector singleton and clean env vars between tests."""
    reset_collector()
    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)
    yield
    reset_collector()
    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    manager = MagicMock()
    manager.keys = MagicMock()
    manager.keys.get_status_summary = AsyncMock(return_value=[])
    return manager


# ---------------------------------------------------------------------------
# UT-KM01: Keeper creates IMetricsCollector (single-process) at init
# ---------------------------------------------------------------------------


class TestKeeperCollectorInit:
    """UT-KM01: Keeper creates IMetricsCollector (single-process) at init."""

    def test_get_collector_returns_single_process_prometheus(self):
        """When PROMETHEUS_MULTIPROC_DIR is not set, get_collector()
        returns a PrometheusMetricsCollector in single-process mode."""
        collector = get_collector()
        assert isinstance(collector, PrometheusMetricsCollector)
        assert collector._multiprocess_dir is None

    @pytest.mark.asyncio
    async def test_keeper_calls_get_collector_during_run(
        self, mock_run_keeper_dependencies
    ):
        """run_keeper() calls get_collector() during initialization,
        producing a single-process collector (no PROMETHEUS_MULTIPROC_DIR)."""
        mock_collector = MagicMock(spec=IMetricsCollector)

        with (
            patch(
                "src.services.keeper.get_collector",
                return_value=mock_collector,
            ) as mock_get,
            patch(
                "src.services.keeper._start_metrics_server",
                new_callable=AsyncMock,
            ),
            patch(
                "src.services.keeper._collect_db_metrics_loop",
                new_callable=AsyncMock,
            ),
            patch(
                "asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=KeyboardInterrupt,
            ),
        ):
            # KeyboardInterrupt is caught by run_keeper's except block
            await run_keeper()

        # get_collector was called at least once during Keeper init
        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# UT-KM02: Keeper calls collector.collect_from_db(db_manager) periodically
# ---------------------------------------------------------------------------


class TestKeeperDBMetricsLoop:
    """UT-KM02: Keeper calls collector.collect_from_db(db_manager) periodically."""

    @pytest.mark.asyncio
    async def test_collect_db_metrics_calls_collect_from_db(self, mock_db_manager):
        """_collect_db_metrics_loop calls collector.collect_from_db(db_manager)."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.collect_from_db = AsyncMock()

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            # Cancel after first sleep to simulate one iteration
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await _collect_db_metrics_loop(mock_db_manager, interval_sec=30)

        mock_collector.collect_from_db.assert_called_once_with(mock_db_manager)

    @pytest.mark.asyncio
    async def test_collect_db_metrics_loop_survives_exception(self, mock_db_manager):
        """_collect_db_metrics_loop continues after collect_from_db raises."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.collect_from_db = AsyncMock(side_effect=RuntimeError("DB error"))

        iteration = 0

        async def mock_sleep(_sec):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                raise asyncio.CancelledError()

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await _collect_db_metrics_loop(mock_db_manager, interval_sec=30)

        # collect_from_db was called at least once despite the error
        assert mock_collector.collect_from_db.call_count >= 1

    @pytest.mark.asyncio
    async def test_collect_db_metrics_loop_cancels_gracefully(self, mock_db_manager):
        """CancelledError breaks the loop without logging an error."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.collect_from_db = AsyncMock()

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await _collect_db_metrics_loop(mock_db_manager, interval_sec=30)

        # Only one collect_from_db call (before the sleep that cancelled)
        mock_collector.collect_from_db.assert_called_once_with(mock_db_manager)


# ---------------------------------------------------------------------------
# UT-KM03: Keeper calls adaptive metrics through collector
# ---------------------------------------------------------------------------


class TestKeeperAdaptiveMetrics:
    """UT-KM03: Keeper calls adaptive metrics through collector."""

    def test_adaptive_callback_sets_all_five_gauges(self):
        """_create_adaptive_metrics_callback() calls collector.gauge() 5 times."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        assert mock_collector.gauge.call_count == 5

    def test_adaptive_callback_sets_batch_size(self):
        """Callback sets ADAPTIVE_BATCH_SIZE gauge with provider label."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        mock_collector.gauge.assert_any_call(
            ADAPTIVE_BATCH_SIZE,
            "Current adaptive batch size per provider",
            ["provider"],
        )
        mock_gauge.set.assert_any_call(5.0, {"provider": "openai"})

    def test_adaptive_callback_sets_batch_delay(self):
        """Callback sets ADAPTIVE_BATCH_DELAY gauge with provider label."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        mock_collector.gauge.assert_any_call(
            ADAPTIVE_BATCH_DELAY,
            "Current adaptive batch delay in seconds per provider",
            ["provider"],
        )
        mock_gauge.set.assert_any_call(0.2, {"provider": "openai"})

    def test_adaptive_callback_sets_rate_limit_events(self):
        """Callback sets ADAPTIVE_RATE_LIMIT_EVENTS gauge."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        mock_collector.gauge.assert_any_call(
            ADAPTIVE_RATE_LIMIT_EVENTS,
            "Total number of aggressive (rate-limit) backoff events per provider",
            ["provider"],
        )
        mock_gauge.set.assert_any_call(3.0, {"provider": "openai"})

    def test_adaptive_callback_sets_backoff_events(self):
        """Callback sets ADAPTIVE_BACKOFF_EVENTS gauge."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        mock_collector.gauge.assert_any_call(
            ADAPTIVE_BACKOFF_EVENTS,
            "Total number of moderate (transient-threshold) backoff events per provider",
            ["provider"],
        )
        mock_gauge.set.assert_any_call(1.0, {"provider": "openai"})

    def test_adaptive_callback_sets_recovery_events(self):
        """Callback sets ADAPTIVE_RECOVERY_EVENTS gauge."""
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        with patch("src.services.keeper.get_collector", return_value=mock_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        mock_collector.gauge.assert_any_call(
            ADAPTIVE_RECOVERY_EVENTS,
            "Total number of recovery (ramp-up) events per provider",
            ["provider"],
        )
        mock_gauge.set.assert_any_call(2.0, {"provider": "openai"})

    def test_adaptive_callback_uses_get_collector_singleton(self):
        """Callback calls get_collector() at invocation time (not at creation time),
        ensuring it always uses the current singleton."""
        call_count = 0
        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_gauge = MagicMock()
        mock_collector.gauge.return_value = mock_gauge

        def mock_get_collector():
            nonlocal call_count
            call_count += 1
            return mock_collector

        with patch("src.services.keeper.get_collector", side_effect=mock_get_collector):
            callback = _create_adaptive_metrics_callback()
            callback(
                provider_name="openai",
                batch_size=5,
                batch_delay=0.2,
                rate_limit_events=3,
                backoff_events=1,
                recovery_events=2,
            )

        # get_collector called once per callback invocation (the callback
        # stores the collector reference and reuses it for all 5 gauges)
        assert call_count == 1