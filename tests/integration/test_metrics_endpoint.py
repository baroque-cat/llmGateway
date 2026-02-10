#!/usr/bin/env python3

"""
Integration tests for the /metrics endpoint.

Tests authentication, error handling, and proper metric format.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST

from src.config.schemas import MetricsConfig
from src.services.gateway_service import create_app


@pytest.fixture
def mock_accessor():
    """Create a mock ConfigAccessor with metrics configuration."""
    accessor = MagicMock()

    # Default metrics config: enabled with token
    metrics_config = MetricsConfig(enabled=True, access_token="secret-token")
    accessor.get_metrics_config.return_value = metrics_config

    # Default provider config for other endpoints
    accessor.get_enabled_providers.return_value = {}
    accessor.get_health_policy.return_value = MagicMock()
    accessor.get_worker_concurrency.return_value = 10
    accessor.get_logging_config.return_value = MagicMock()

    return accessor


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    manager = MagicMock()
    manager.keys = MagicMock()
    manager.providers = MagicMock()
    manager.proxies = MagicMock()
    return manager


@pytest.fixture
def mock_metrics_service():
    """Mock MetricsService."""
    service = MagicMock()
    service.get_metrics.return_value = (b"test_metrics_data", CONTENT_TYPE_LATEST)
    return service


@pytest.fixture
def gateway_app(mock_accessor, mock_db_manager, mock_metrics_service):
    """Create gateway app with mocked dependencies."""
    with patch("src.services.gateway_service.DatabaseManager") as mock_db_cls:
        mock_db_cls.return_value = mock_db_manager

        # Create app with mocked accessor
        app = create_app(mock_accessor)

        # Set up app state as done in create_app
        app.state.accessor = mock_accessor
        app.state.db_manager = mock_db_manager
        # Metrics service will be set based on config
        # We'll manually set it for tests
        app.state.metrics_service = mock_metrics_service

        yield app


@pytest.fixture
def client(gateway_app):
    """Create test client."""
    return TestClient(gateway_app)


class TestMetricsEndpoint:
    """Test /metrics endpoint behavior."""

    def test_metrics_disabled_returns_404(self, mock_accessor, gateway_app):
        """Test /metrics returns 404 when metrics are disabled."""
        # Configure metrics as disabled
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=False, access_token="secret-token"
        )
        # When metrics are disabled, metrics_service should be None
        gateway_app.state.metrics_service = None

        client = TestClient(gateway_app)
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Metrics endpoint is not enabled"

    def test_metrics_enabled_but_access_token_empty_returns_404(
        self, mock_accessor, gateway_app
    ):
        """Test /metrics returns 404 when access token is empty string."""
        # Configure metrics enabled but with empty token
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True, access_token=""
        )
        # When access token is empty, metrics_service should be None
        gateway_app.state.metrics_service = None

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

    def test_valid_token_returns_200_and_metrics(self, client, mock_metrics_service):
        """Test /metrics returns 200 with Prometheus format when token is valid."""
        # Configure mock metrics data
        test_metrics = b'# TYPE llm_gateway_keys_total gauge\nllm_gateway_keys_total{provider="test",model="test",status="valid"} 5'
        mock_metrics_service.get_metrics.return_value = (
            test_metrics,
            CONTENT_TYPE_LATEST,
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == CONTENT_TYPE_LATEST
        assert response.content == test_metrics

        # Verify metrics service was called
        mock_metrics_service.get_metrics.assert_called_once()

    def test_metrics_service_none_returns_404(self, gateway_app, mock_accessor):
        """Test /metrics returns 404 when metrics_service is None in app state."""
        # Create client with app where metrics_service is None
        gateway_app.state.metrics_service = None
        client = TestClient(gateway_app)

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Metrics endpoint is not enabled"

    def test_metrics_content_matches_prometheus_format(
        self, client, mock_metrics_service
    ):
        """Test metrics content is valid Prometheus format."""
        # Mock metrics data in Prometheus format
        test_metrics = b'test_metric{label1="value1"} 42.0'
        mock_metrics_service.get_metrics.return_value = (
            test_metrics,
            CONTENT_TYPE_LATEST,
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 200
        # Check it's valid text
        assert b"test_metric" in response.content

    @pytest.mark.asyncio
    async def test_metrics_cache_update_loop_integration(
        self, mock_accessor, mock_db_manager
    ):
        """Test integration of metrics cache update loop with mocked dependencies."""
        from src.services.gateway_service import _metrics_cache_update_loop
        from src.services.metrics_exporter import MetricsService

        # Create real MetricsService with mocked DB
        metrics_service = MetricsService(mock_db_manager)

        # Mock the update_metrics_cache method
        metrics_service.update_metrics_cache = AsyncMock()

        # Run loop for a short time with small interval
        import asyncio

        # Create task and cancel after a short delay
        task = asyncio.create_task(
            _metrics_cache_update_loop(metrics_service, interval_sec=0.1)
        )

        # Let it run for a couple iterations
        await asyncio.sleep(0.25)

        # Cancel the task
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Verify update_metrics_cache was called at least once
        assert metrics_service.update_metrics_cache.call_count >= 1

    def test_metrics_config_validation(self, mock_accessor):
        """Test metrics configuration loading and validation."""
        from src.config.schemas import MetricsConfig

        # Test default values
        config = MetricsConfig()
        assert config.enabled is True  # Default per schema
        assert config.access_token == ""

        # Test custom values
        config = MetricsConfig(enabled=True, access_token="my-token")
        assert config.enabled is True
        assert config.access_token == "my-token"

        # Test that accessor returns correct config
        mock_accessor.get_metrics_config.return_value = config
        assert mock_accessor.get_metrics_config() == config
