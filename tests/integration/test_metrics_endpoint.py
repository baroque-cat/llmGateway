#!/usr/bin/env python3

"""Integration tests for the Gateway /metrics endpoint.

Rewritten for the auth-proxy architecture:
  - Gateway /metrics validates auth via src.metrics.auth domain functions
  - Proxies to http://keeper:9090/metrics via httpx.AsyncClient
  - MetricsAuthError → HTTPException, httpx.TransportError → HTTPException(502)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.schemas import GatewayConfig, MetricsConfig
from src.services.gateway.gateway_service import create_app

# ---------------------------------------------------------------------------
# Helper: real async mock for httpx.AsyncClient
# ---------------------------------------------------------------------------


class _MockAsyncClient:
    """A real async-context-manager mock for ``httpx.AsyncClient``.

    ``AsyncMock`` does not reliably propagate configured child mocks
    through ``__aenter__`` when used with Starlette's ``TestClient``.
    This class uses genuine ``async`` methods so the ``await`` chain
    resolves correctly inside the synchronous test runner.
    """

    def __init__(
        self,
        get_response: MagicMock | None = None,
        get_side_effect: Exception | None = None,
    ) -> None:
        self._get_response = get_response
        self._get_side_effect = get_side_effect

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    async def get(self, url: str, **kwargs) -> MagicMock:
        if self._get_side_effect is not None:
            raise self._get_side_effect
        return self._get_response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def gateway_app(mock_accessor, mock_db_manager):
    """Create gateway app with mocked dependencies."""
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
        patch("src.services.gateway.gateway_service.HttpClientFactory") as mock_hcf_cls,
        patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
        patch(
            "src.services.gateway.gateway_service._cache_refresh_loop",
            new=AsyncMock(),
        ),
    ):
        mock_dm_cls.return_value = mock_db_manager
        mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
        mock_gc_cls.return_value.populate_caches = AsyncMock()
        mock_hcf_cls.return_value.close_all = AsyncMock()

        app = create_app(mock_accessor)
        app.state.accessor = mock_accessor
        yield app


@pytest.fixture
def client(gateway_app):
    """Create test client."""
    return TestClient(gateway_app)


# ---------------------------------------------------------------------------
# Auth-proxy tests
# ---------------------------------------------------------------------------


class TestMetricsEndpointAuthProxy:
    """Integration tests for Gateway /metrics as auth-proxy to Keeper."""

    # IT-MP01: Metrics disabled → 404
    def test_metrics_disabled_returns_404(self, mock_accessor, client):
        """GET /metrics with metrics disabled returns 404."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=False, access_token="secret-token"
        )

        response = client.get(
            "/metrics", headers={"Authorization": "Bearer secret-token"}
        )

        assert response.status_code == 404
        assert "Metrics endpoint is disabled" in response.json()["detail"]

    # IT-MP02: Empty token → 404
    def test_empty_access_token_returns_404(self, mock_accessor, client):
        """GET /metrics with empty access_token returns 404."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True, access_token=""
        )

        response = client.get("/metrics")

        assert response.status_code == 404
        assert "Metrics endpoint is disabled" in response.json()["detail"]

    # IT-MP03: Missing Authorization → 401
    def test_missing_authorization_returns_401(self, client):
        """GET /metrics without Authorization header returns 401."""
        response = client.get("/metrics")

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    # IT-MP04: Invalid scheme → 401
    def test_invalid_auth_scheme_returns_401(self, client):
        """GET /metrics with Basic auth scheme returns 401."""
        response = client.get(
            "/metrics", headers={"Authorization": "Basic secret-token"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    # IT-MP05: Malformed header → 401
    def test_malformed_bearer_header_returns_401(self, client):
        """GET /metrics with 'Bearer' (no token value) returns 401."""
        response = client.get("/metrics", headers={"Authorization": "Bearer"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or invalid Authorization header"

    # IT-MP06: Invalid token → 403
    def test_invalid_token_returns_403(self, client):
        """GET /metrics with wrong Bearer token returns 403."""
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer wrong-token"}
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid metrics access token"

    # IT-MP07: Valid token + Keeper available → 200 with Keeper content
    def test_valid_token_keeper_available_returns_200(self, client):
        """GET /metrics with valid token proxies to Keeper and returns 200."""
        mock_response = MagicMock()
        mock_response.content = (
            b"# HELP test_metric A test\n"
            b"# TYPE test_metric gauge\n"
            b"test_metric 42.0"
        )
        mock_response.headers = {
            "content-type": "text/plain; version=0.0.4; charset=utf-8",
        }

        mock_client = _MockAsyncClient(get_response=mock_response)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            response = client.get(
                "/metrics", headers={"Authorization": "Bearer secret-token"}
            )

            assert response.status_code == 200
            assert b"test_metric" in response.content

    # IT-MP08: Valid token + Keeper unavailable → 502
    def test_valid_token_keeper_unavailable_returns_502(self, client):
        """GET /metrics with valid token but Keeper down returns 502."""
        mock_client = _MockAsyncClient(
            get_side_effect=httpx.ConnectError("Connection refused")
        )

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            response = client.get(
                "/metrics", headers={"Authorization": "Bearer secret-token"}
            )

            assert response.status_code == 502
            assert response.json()["detail"] == "Keeper metrics unavailable"

    # IT-MP09: Valid token + Keeper timeout → 502
    def test_valid_token_keeper_timeout_returns_502(self, client):
        """GET /metrics with valid token but Keeper timeout returns 502."""
        mock_client = _MockAsyncClient(
            get_side_effect=httpx.TimeoutException("Request timed out")
        )

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            response = client.get(
                "/metrics", headers={"Authorization": "Bearer secret-token"}
            )

            assert response.status_code == 502
            assert response.json()["detail"] == "Keeper metrics unavailable"

    # IT-MP10: Keeper content-type preserved in response
    def test_keeper_content_type_preserved(self, client):
        """Gateway response preserves Keeper's content-type header."""
        mock_response = MagicMock()
        mock_response.content = b"metric 1.0"
        mock_response.headers = {
            "content-type": "text/plain; version=0.0.4; charset=utf-8",
        }

        mock_client = _MockAsyncClient(get_response=mock_response)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            response = client.get(
                "/metrics", headers={"Authorization": "Bearer secret-token"}
            )

            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]



