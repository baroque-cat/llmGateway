#!/usr/bin/env python3

"""Integration tests for Gateway multiprocess metrics.

Tests:
  IT-GM01: Gateway /metrics with auth → contains request-level metrics
  IT-GM02: Gateway /metrics → does NOT contain llm_gateway_keys_total
  IT-GM03: Gateway /metrics → does NOT contain llm_gateway_adaptive_batch_size
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config.schemas import GatewayConfig, MetricsConfig

from src.metrics import get_collector, reset_collector
from src.metrics.backends.memory import MemoryMetricsCollector
from src.metrics.registry import (
    ADAPTIVE_BATCH_SIZE,
    KEY_STATUS_TOTAL,
    REQUESTS_TOTAL,
)
from src.services.gateway.gateway_service import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_accessor(
    workers: int = 1,
    metrics_enabled: bool = True,
    metrics_token: str = "secret-token",
) -> MagicMock:
    """Create a mock ConfigAccessor."""
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


@pytest.fixture
def memory_collector():
    """Create a MemoryMetricsCollector for test isolation."""
    os.environ["METRICS_BACKEND"] = "memory"
    reset_collector()
    collector = get_collector()
    assert isinstance(collector, MemoryMetricsCollector)
    return collector


@pytest.fixture
def gateway_app_with_memory_collector(memory_collector):
    """Create a Gateway app that uses MemoryMetricsCollector."""
    accessor = _make_mock_accessor(workers=1)

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new=AsyncMock(),
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new=AsyncMock(),
        ),
        patch("src.services.gateway.gateway_service.DatabaseManager") as mock_dm_cls,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as mock_hcf_cls,
        patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
        patch(
            "src.services.gateway.gateway_service._cache_refresh_loop",
            new=AsyncMock(),
        ),
    ):
        mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
        mock_gc_cls.return_value.populate_caches = AsyncMock()
        mock_hcf_cls.return_value.close_all = AsyncMock()

        app = create_app(accessor)
        # Ensure accessor is available for auth validation
        app.state.accessor = accessor
        yield app


# ---------------------------------------------------------------------------
# IT-GM01: Gateway /metrics with auth → contains request-level metrics
# ---------------------------------------------------------------------------


class TestGatewayMultiprocessMetrics:
    """Integration tests for Gateway /metrics with multiprocess collector."""

    def test_it_gm01_metrics_with_auth_contains_request_metrics(
        self, gateway_app_with_memory_collector, memory_collector
    ):
        """IT-GM01: Gateway /metrics with auth → contains request-level metrics."""
        # Register a request-level metric on the collector
        memory_collector.counter(
            REQUESTS_TOTAL,
            "Total number of gateway requests",
            ["provider", "model"],
        ).inc(1, {"provider": "openai", "model": "gpt-4o"})

        client = TestClient(gateway_app_with_memory_collector)
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )

        assert response.status_code == 200

        # MemoryMetricsCollector returns JSON
        data = json.loads(response.text)
        metrics = data["metrics"]

        # Find request-level metrics
        request_metrics = [m for m in metrics if m["name"] == REQUESTS_TOTAL]
        assert len(request_metrics) >= 1
        assert request_metrics[0]["value"] == 1.0

    def test_it_gm02_metrics_does_not_contain_keys_total(
        self, gateway_app_with_memory_collector, memory_collector
    ):
        """IT-GM02: Gateway /metrics → does NOT contain llm_gateway_keys_total.

        Key-status metrics are the Keeper's responsibility; the Gateway
        should not export them.
        """
        # Register only request-level metrics (no key-status)
        memory_collector.counter(
            REQUESTS_TOTAL,
            "Total number of gateway requests",
            ["provider"],
        ).inc(5, {"provider": "openai"})

        client = TestClient(gateway_app_with_memory_collector)
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )

        assert response.status_code == 200

        data = json.loads(response.text)
        metrics = data["metrics"]

        key_status_metrics = [m for m in metrics if m["name"] == KEY_STATUS_TOTAL]
        assert len(key_status_metrics) == 0, (
            f"Gateway /metrics should NOT contain {KEY_STATUS_TOTAL}, "
            f"but found: {key_status_metrics}"
        )

    def test_it_gm03_metrics_does_not_contain_adaptive_batch_size(
        self, gateway_app_with_memory_collector, memory_collector
    ):
        """IT-GM03: Gateway /metrics → does NOT contain
        llm_gateway_adaptive_batch_size.

        Adaptive metrics are the Keeper's responsibility; the Gateway
        should not export them.
        """
        # Register only request-level metrics (no adaptive)
        memory_collector.counter(
            REQUESTS_TOTAL,
            "Total number of gateway requests",
            ["provider"],
        ).inc(5, {"provider": "openai"})

        client = TestClient(gateway_app_with_memory_collector)
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )

        assert response.status_code == 200

        data = json.loads(response.text)
        metrics = data["metrics"]

        adaptive_metrics = [m for m in metrics if m["name"] == ADAPTIVE_BATCH_SIZE]
        assert len(adaptive_metrics) == 0, (
            f"Gateway /metrics should NOT contain {ADAPTIVE_BATCH_SIZE}, "
            f"but found: {adaptive_metrics}"
        )

    def test_gateway_metrics_empty_when_no_request_metrics_registered(
        self, gateway_app_with_memory_collector, memory_collector
    ):
        """Gateway /metrics returns valid JSON even when no metrics are
        registered (empty collector)."""
        client = TestClient(gateway_app_with_memory_collector)
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )

        assert response.status_code == 200
        data = json.loads(response.text)
        assert "metrics" in data
        # Empty collector → empty metrics list
        assert len(data["metrics"]) == 0