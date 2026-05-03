#!/usr/bin/env python3

"""Unit tests for Gateway multiprocess metrics setup.

Tests:
  UT-GM01: Gateway lifespan creates PrometheusMetricsCollector with
           PROMETHEUS_MULTIPROC_DIR when workers > 1
  UT-GM02: Gateway lifespan creates single-process collector when workers == 1
  UT-GM03: Gateway /metrics uses collector.generate_metrics() instead of
           MetricsService.get_metrics()
  UT-GM04: Gateway lifespan does NOT call collector.collect_from_db()
"""

import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from src.config.schemas import GatewayConfig, MetricsConfig
from src.metrics import get_collector, reset_collector
from src.metrics.backends.prometheus import PrometheusMetricsCollector
from src.services.gateway.gateway_service import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_accessor(
    workers: int = 1,
    metrics_enabled: bool = True,
    metrics_token: str = "secret-token",
) -> MagicMock:
    """Create a mock ConfigAccessor with specified workers and metrics config."""
    accessor = MagicMock()

    gw_config = GatewayConfig(workers=workers)
    accessor.get_gateway_config.return_value = gw_config

    metrics_config = MetricsConfig(enabled=metrics_enabled, access_token=metrics_token)
    accessor.get_metrics_config.return_value = metrics_config

    accessor.get_enabled_providers.return_value = {}
    accessor.get_database_dsn.return_value = "postgresql://test:test@localhost/test"
    accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=5)

    return accessor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_collector_and_env():
    """Reset the collector singleton and clean env vars between tests."""
    reset_collector()
    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)
    yield
    reset_collector()
    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# UT-GM01: Gateway lifespan creates multiprocess collector when workers > 1
# ---------------------------------------------------------------------------


class TestGatewayMultiprocessSetup:
    """UT-GM01: Gateway lifespan creates PrometheusMetricsCollector with
    PROMETHEUS_MULTIPROC_DIR when workers > 1."""

    def test_multiprocess_dir_set_when_workers_gt_1(self):
        """When workers > 1, the lifespan sets PROMETHEUS_MULTIPROC_DIR
        and creates a multiprocess collector."""
        accessor = _make_mock_accessor(workers=4)
        tmp_dir = tempfile.mkdtemp(prefix="prometheus_multiproc_test_")

        # Pre-set PROMETHEUS_MULTIPROC_DIR to our temp dir
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmp_dir
        reset_collector()

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory"
            ) as mock_hcf_cls,
            patch(
                "src.services.gateway.gateway_service.GatewayCache"
            ) as mock_gc_cls,
            patch(
                "src.services.gateway.gateway_service._cache_refresh_loop",
                new=AsyncMock(),
            ),
        ):
            mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
            mock_gc_cls.return_value.populate_caches = AsyncMock()
            # close_all() is called during lifespan shutdown — must be async
            mock_hcf_cls.return_value.close_all = AsyncMock()

            app = create_app(accessor)

            with TestClient(app):
                # Lifespan has run; check the collector
                collector = get_collector()
                assert isinstance(collector, PrometheusMetricsCollector)
                assert collector._multiprocess_dir is not None

        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_reset_collector_called_when_workers_gt_1(self):
        """When workers > 1, the lifespan calls reset_collector() so the
        factory picks up the multiprocess env var."""
        accessor = _make_mock_accessor(workers=4)
        tmp_dir = tempfile.mkdtemp(prefix="prometheus_multiproc_test_")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmp_dir
        reset_collector()

        with patch(
            "src.services.gateway.gateway_service.reset_collector"
        ) as mock_reset:
            with (
                patch(
                    "src.services.gateway.gateway_service.database.init_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.database.close_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.DatabaseManager"
                ) as mock_dm_cls,
                patch(
                    "src.services.gateway.gateway_service.HttpClientFactory"
                ) as mock_hcf_cls,
                patch(
                    "src.services.gateway.gateway_service.GatewayCache"
                ) as mock_gc_cls,
                patch(
                    "src.services.gateway.gateway_service._cache_refresh_loop",
                    new=AsyncMock(),
                ),
            ):
                mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
                mock_gc_cls.return_value.populate_caches = AsyncMock()
                mock_hcf_cls.return_value.close_all = AsyncMock()

                app = create_app(accessor)

                with TestClient(app):
                    mock_reset.assert_called_once()

        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# UT-GM02: Gateway lifespan creates single-process collector when workers == 1
# ---------------------------------------------------------------------------


class TestGatewaySingleProcessSetup:
    """UT-GM02: Gateway lifespan creates single-process collector when
    workers == 1."""

    def test_single_process_collector_when_workers_eq_1(self):
        """When workers == 1, the lifespan does NOT set PROMETHEUS_MULTIPROC_DIR
        and creates a single-process collector."""
        accessor = _make_mock_accessor(workers=1)
        reset_collector()
        os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory"
            ) as mock_hcf_cls,
            patch(
                "src.services.gateway.gateway_service.GatewayCache"
            ) as mock_gc_cls,
            patch(
                "src.services.gateway.gateway_service._cache_refresh_loop",
                new=AsyncMock(),
            ),
        ):
            mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
            mock_gc_cls.return_value.populate_caches = AsyncMock()
            mock_hcf_cls.return_value.close_all = AsyncMock()

            app = create_app(accessor)

            with TestClient(app):
                collector = get_collector()
                assert isinstance(collector, PrometheusMetricsCollector)
                assert collector._multiprocess_dir is None

    def test_reset_collector_not_called_when_workers_eq_1(self):
        """When workers == 1, the lifespan does NOT call reset_collector()."""
        accessor = _make_mock_accessor(workers=1)
        reset_collector()
        os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

        with patch(
            "src.services.gateway.gateway_service.reset_collector"
        ) as mock_reset:
            with (
                patch(
                    "src.services.gateway.gateway_service.database.init_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.database.close_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.DatabaseManager"
                ) as mock_dm_cls,
                patch(
                    "src.services.gateway.gateway_service.HttpClientFactory"
                ) as mock_hcf_cls,
                patch(
                    "src.services.gateway.gateway_service.GatewayCache"
                ) as mock_gc_cls,
                patch(
                    "src.services.gateway.gateway_service._cache_refresh_loop",
                    new=AsyncMock(),
                ),
            ):
                mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
                mock_gc_cls.return_value.populate_caches = AsyncMock()
                mock_hcf_cls.return_value.close_all = AsyncMock()

                app = create_app(accessor)

                with TestClient(app):
                    mock_reset.assert_not_called()


# ---------------------------------------------------------------------------
# UT-GM03: Gateway /metrics uses collector.generate_metrics()
# ---------------------------------------------------------------------------


class TestGatewayMetricsEndpointUsesCollector:
    """UT-GM03: Gateway /metrics uses collector.generate_metrics() instead
    of MetricsService.get_metrics()."""

    def test_metrics_endpoint_calls_generate_metrics(self):
        """The /metrics endpoint calls get_collector().generate_metrics()
        and returns the result."""
        from src.core.interfaces import IMetricsCollector

        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.generate_metrics.return_value = (
            b"test_metric 42.0",
            "text/plain; version=0.0.4; charset=utf-8",
        )

        accessor = _make_mock_accessor()
        reset_collector()

        with patch(
            "src.services.gateway.gateway_service.get_collector",
            return_value=mock_collector,
        ):
            with (
                patch(
                    "src.services.gateway.gateway_service.database.init_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.database.close_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.DatabaseManager"
                ) as mock_dm_cls,
                patch(
                    "src.services.gateway.gateway_service.HttpClientFactory"
                ) as mock_hcf_cls,
                patch(
                    "src.services.gateway.gateway_service.GatewayCache"
                ) as mock_gc_cls,
                patch(
                    "src.services.gateway.gateway_service._cache_refresh_loop",
                    new=AsyncMock(),
                ),
            ):
                mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
                mock_gc_cls.return_value.populate_caches = AsyncMock()
                mock_hcf_cls.return_value.close_all = AsyncMock()

                app = create_app(accessor)
                # Manually set accessor on state (lifespan may not run fully)
                app.state.accessor = accessor

                client = TestClient(app)
                response = client.get(
                    "/metrics",
                    headers={"Authorization": "Bearer secret-token"},
                )

                assert response.status_code == 200
                assert b"test_metric 42.0" in response.content
                mock_collector.generate_metrics.assert_called_once()


# ---------------------------------------------------------------------------
# UT-GM04: Gateway lifespan does NOT call collector.collect_from_db()
# ---------------------------------------------------------------------------


class TestGatewayLifespanNoCollectFromDb:
    """UT-GM04: Gateway lifespan does NOT call collector.collect_from_db()."""

    def test_lifespan_does_not_call_collect_from_db(self):
        """The Gateway lifespan never calls collector.collect_from_db();
        that is the Keeper's responsibility."""
        from src.core.interfaces import IMetricsCollector

        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.collect_from_db = AsyncMock()
        mock_collector.generate_metrics.return_value = (
            b"test_metric 1.0",
            "text/plain; version=0.0.4; charset=utf-8",
        )

        accessor = _make_mock_accessor(workers=1)
        reset_collector()

        with patch(
            "src.services.gateway.gateway_service.get_collector",
            return_value=mock_collector,
        ):
            with (
                patch(
                    "src.services.gateway.gateway_service.database.init_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.database.close_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.DatabaseManager"
                ) as mock_dm_cls,
                patch(
                    "src.services.gateway.gateway_service.HttpClientFactory"
                ) as mock_hcf_cls,
                patch(
                    "src.services.gateway.gateway_service.GatewayCache"
                ) as mock_gc_cls,
                patch(
                    "src.services.gateway.gateway_service._cache_refresh_loop",
                    new=AsyncMock(),
                ),
            ):
                mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
                mock_gc_cls.return_value.populate_caches = AsyncMock()
                mock_hcf_cls.return_value.close_all = AsyncMock()

                app = create_app(accessor)

                with TestClient(app):
                    # The lifespan has run; collect_from_db should NOT have been called
                    mock_collector.collect_from_db.assert_not_called()

    def test_lifespan_does_not_call_collect_from_db_multiprocess(self):
        """Even in multiprocess mode, the lifespan does NOT call
        collect_from_db."""
        from src.core.interfaces import IMetricsCollector

        mock_collector = MagicMock(spec=IMetricsCollector)
        mock_collector.collect_from_db = AsyncMock()
        mock_collector.generate_metrics.return_value = (
            b"test_metric 1.0",
            "text/plain; version=0.0.4; charset=utf-8",
        )

        accessor = _make_mock_accessor(workers=4)
        tmp_dir = tempfile.mkdtemp(prefix="prometheus_multiproc_test_")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmp_dir
        reset_collector()

        with patch(
            "src.services.gateway.gateway_service.get_collector",
            return_value=mock_collector,
        ):
            with (
                patch(
                    "src.services.gateway.gateway_service.database.init_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.database.close_db_pool",
                    new=AsyncMock(),
                ),
                patch(
                    "src.services.gateway.gateway_service.DatabaseManager"
                ) as mock_dm_cls,
                patch(
                    "src.services.gateway.gateway_service.HttpClientFactory"
                ) as mock_hcf_cls,
                patch(
                    "src.services.gateway.gateway_service.GatewayCache"
                ) as mock_gc_cls,
                patch(
                    "src.services.gateway.gateway_service._cache_refresh_loop",
                    new=AsyncMock(),
                ),
            ):
                mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
                mock_gc_cls.return_value.populate_caches = AsyncMock()
                mock_hcf_cls.return_value.close_all = AsyncMock()

                app = create_app(accessor)

                with TestClient(app):
                    mock_collector.collect_from_db.assert_not_called()

        shutil.rmtree(tmp_dir, ignore_errors=True)