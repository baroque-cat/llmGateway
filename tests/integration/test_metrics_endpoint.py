#!/usr/bin/env python3

"""Integration tests for the Gateway /metrics endpoint.

Rewritten to use the new collector-based endpoint:
  - Gateway /metrics now exports only request-level metrics
  - Uses get_collector().generate_metrics() instead of MetricsService
  - No KeyStatusCollector or MetricsService references
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config.schemas import GatewayConfig, MetricsConfig
from src.core.interfaces import IMetricsCollector
from src.metrics import get_collector, reset_collector

from src.services.gateway.gateway_service import create_app


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
def mock_accessor():
    """Create a mock ConfigAccessor with metrics configuration."""
    accessor = MagicMock()

    gw_config = GatewayConfig(workers=1)
    accessor.get_gateway_config.return_value = gw_config

    metrics_config = MetricsConfig(enabled=True, access_token="secret-token")
    accessor.get_metrics_config.return_value = metrics_config

    accessor.get_enabled_providers.return_value = {}
    accessor.get_database_dsn.return_value = "postgresql://test:test@localhost/test"
    accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=5)

    return accessor


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    manager = MagicMock()
    manager.wait_for_schema_ready = AsyncMock()
    manager.keys = MagicMock()
    manager.providers = MagicMock()
    manager.proxies = MagicMock()
    return manager


@pytest.fixture
def mock_collector():
    """Create a mock IMetricsCollector."""
    collector = MagicMock(spec=IMetricsCollector)
    collector.generate_metrics.return_value = (
        b"# HELP test_metric A test\n# TYPE test_metric gauge\ntest_metric 42.0",
        "text/plain; version=0.0.4; charset=utf-8",
    )
    collector.collect_from_db = AsyncMock()
    return collector


@pytest.fixture
def gateway_app(mock_accessor, mock_db_manager, mock_collector):
    """Create gateway app with mocked dependencies and collector."""
    os.environ["METRICS_BACKEND"] = "memory"
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
        patch("src.services.gateway.gateway_service.DatabaseManager") as mock_dm_cls,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as mock_hcf_cls,
        patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
        patch(
            "src.services.gateway.gateway_service._cache_refresh_loop",
            new=AsyncMock(),
        ),
        patch(
            "src.services.gateway.gateway_service.get_collector",
            return_value=mock_collector,
        ),
    ):
        mock_dm_cls.return_value = mock_db_manager
        mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
        mock_gc_cls.return_value.populate_caches = AsyncMock()
        mock_hcf_cls.return_value.close_all = AsyncMock()

        app = create_app(mock_accessor)
        # Ensure accessor is set for auth validation
        app.state.accessor = mock_accessor
        yield app


@pytest.fixture
def client(gateway_app):
    """Create test client."""
    return TestClient(gateway_app)


# ---------------------------------------------------------------------------
# Auth tests (adapted for new collector-based endpoint)
# ---------------------------------------------------------------------------


class TestMetricsEndpointAuth:
    """Test /metrics endpoint authentication."""

    def test_metrics_disabled_returns_404(self, mock_accessor, gateway_app):
        """Test /metrics returns 404 when metrics are disabled."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=False, access_token="secret-token"
        )

        client = TestClient(gateway_app)
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 404
        assert "Metrics endpoint is disabled" in response.json()["detail"]

    def test_metrics_enabled_but_access_token_empty_returns_404(
        self, mock_accessor, gateway_app
    ):
        """When access_token is empty, the endpoint is treated as disabled.

        An empty access_token means metrics are not configured for access,
        so the endpoint returns 404 regardless of whether an Authorization
        header is present.
        """
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True, access_token=""
        )

        client = TestClient(gateway_app)
        response = client.get("/metrics")
        assert response.status_code == 404
        assert response.json()["detail"] == "Metrics endpoint is not enabled"

    def test_missing_authorization_header_returns_401(self, client):
        """Test /metrics returns 401 when Authorization header is missing."""
        response = client.get("/metrics")

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    def test_invalid_authorization_scheme_returns_401(self, client):
        """Test /metrics returns 401 when Authorization scheme is not Bearer."""
        response = client.get(
            "/metrics", headers={"Authorization": "Basic secret-token"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    def test_malformed_authorization_header_returns_401(self, client):
        """Test /metrics returns 401 when Authorization header is malformed."""
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer"}
        )  # Missing token

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    def test_invalid_token_returns_403(self, client):
        """Test /metrics returns 403 when token is invalid."""
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer wrong-token"}
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid metrics access token"

    def test_valid_token_returns_200_and_metrics(self, client, mock_collector):
        """Test /metrics returns 200 with metrics when token is valid."""
        test_metrics = b'test_metric{label1="value1"} 42.0'
        mock_collector.generate_metrics.return_value = (
            test_metrics,
            "text/plain; version=0.0.4; charset=utf-8",
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 200
        assert b"test_metric" in response.content

        # Verify collector.generate_metrics was called (not MetricsService)
        mock_collector.generate_metrics.assert_called_once()


# ---------------------------------------------------------------------------
# Collector-based endpoint tests
# ---------------------------------------------------------------------------


class TestMetricsEndpointCollector:
    """Test /metrics endpoint uses IMetricsCollector.generate_metrics()."""

    def test_endpoint_calls_generate_metrics_not_metrics_service(
        self, client, mock_collector
    ):
        """The /metrics endpoint uses collector.generate_metrics()
        instead of MetricsService.get_metrics()."""
        mock_collector.generate_metrics.return_value = (
            b"llm_gateway_requests_total 5",
            "text/plain; version=0.0.4; charset=utf-8",
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 200
        mock_collector.generate_metrics.assert_called_once()

    def test_endpoint_returns_collector_content_type(
        self, client, mock_collector
    ):
        """The /metrics endpoint returns the content type from
        collector.generate_metrics()."""
        mock_collector.generate_metrics.return_value = (
            b"metric 1.0",
            "text/plain; version=0.0.4; charset=utf-8",
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_endpoint_with_memory_collector_returns_json(self):
        """When using MemoryMetricsCollector, the endpoint returns JSON."""
        os.environ["METRICS_BACKEND"] = "memory"
        reset_collector()

        accessor = MagicMock()
        accessor.get_gateway_config.return_value = GatewayConfig(workers=1)
        accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True, access_token="test-token"
        )
        accessor.get_enabled_providers.return_value = {}
        accessor.get_database_dsn.return_value = "postgresql://test:test@localhost/test"
        accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=5)

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
            app.state.accessor = accessor

            # Register a metric on the real MemoryMetricsCollector
            real_collector = get_collector()
            real_collector.counter(
                "llm_gateway_requests_total",
                "Total number of gateway requests",
                ["provider"],
            ).inc(3, {"provider": "openai"})

            client = TestClient(app)
            response = client.get(
                "/metrics", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            assert "application/json" in response.headers["content-type"]

            import json

            data = json.loads(response.text)
            assert "metrics" in data


# ---------------------------------------------------------------------------
# MetricsConfig validation (unchanged — no source code dependency)
# ---------------------------------------------------------------------------


class TestMetricsConfigValidation:
    """Test metrics configuration loading and validation."""

    def test_metrics_config_defaults(self):
        """MetricsConfig has correct default values."""
        config = MetricsConfig()
        assert config.enabled is True
        assert config.access_token == ""

    def test_metrics_config_custom_values(self):
        """MetricsConfig accepts custom values."""
        config = MetricsConfig(enabled=True, access_token="my-token")
        assert config.enabled is True
        assert config.access_token == "my-token"

    def test_accessor_returns_metrics_config(self, mock_accessor):
        """ConfigAccessor.get_metrics_config() returns the config."""
        config = MetricsConfig(enabled=True, access_token="test")
        mock_accessor.get_metrics_config.return_value = config
        assert mock_accessor.get_metrics_config() == config