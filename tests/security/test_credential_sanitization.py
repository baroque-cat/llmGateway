#!/usr/bin/env python3

"""
Security tests for credential sanitization in the gateway.

Verifies that:
- _sanitize_headers masks Authorization, x-goog-api-key, x-api-key
- _sanitize_body redacts api_key fields in JSON
- _prepare_proxy_headers strips client auth headers
- /metrics endpoint requires valid token (403 on invalid)
- /metrics endpoint returns 404 when disabled
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.config.schemas import ProviderConfig
from src.services.gateway.gateway_service import (
    _sanitize_body,
    _sanitize_headers,
)

# ---------------------------------------------------------------------------
# Header sanitization
# ---------------------------------------------------------------------------


class TestSanitizeHeaders:
    """Tests for _sanitize_headers masking sensitive headers."""

    def test_sanitize_headers_removes_authorization(self) -> None:
        """SEC-SAN-01: _sanitize_headers masks Authorization header value."""
        headers = {"authorization": "Bearer secret", "content-type": "application/json"}
        result = _sanitize_headers(headers)
        assert result["authorization"] == "Bearer ***"
        assert result["content-type"] == "application/json"

    def test_sanitize_headers_removes_x_goog_api_key(self) -> None:
        """SEC-SAN-02: _sanitize_headers masks x-goog-api-key header."""
        headers = {"x-goog-api-key": "AIzaSyD...", "accept": "application/json"}
        result = _sanitize_headers(headers)
        assert result["x-goog-api-key"] == "***"
        assert result["accept"] == "application/json"

    def test_sanitize_headers_removes_x_api_key(self) -> None:
        """SEC-SAN-03: _sanitize_headers masks x-api-key header."""
        headers = {"x-api-key": "sk-ant-...", "user-agent": "curl/7.0"}
        result = _sanitize_headers(headers)
        assert result["x-api-key"] == "***"
        assert result["user-agent"] == "curl/7.0"


# ---------------------------------------------------------------------------
# Body sanitization
# ---------------------------------------------------------------------------


class TestSanitizeBody:
    """Tests for _sanitize_body redacting sensitive fields."""

    def test_sanitize_body_redacts_api_key_field(self) -> None:
        """SEC-SAN-04: _sanitize_body masks api_key in JSON body."""
        body = b'{"api_key":"sk-123","model":"gpt"}'
        result = _sanitize_body(body, "openai_like")
        assert "sk-123" not in result
        assert '"api_key": "***"' in result or '"api_key":"***"' in result
        assert "gpt" in result


# ---------------------------------------------------------------------------
# Proxy header preparation (strips client auth)
# ---------------------------------------------------------------------------


class TestPrepareProxyHeaders:
    """Tests for _prepare_proxy_headers stripping client auth headers."""

    def test_prepare_proxy_headers_strips_client_auth(self) -> None:
        """SEC-SAN-05: _prepare_proxy_headers removes client authorization header."""
        # Use a concrete provider implementation that has _prepare_proxy_headers
        from src.providers.impl.openai_like import OpenAILikeProvider

        config = ProviderConfig(provider_type="openai_like")
        provider = OpenAILikeProvider("test_instance", config)

        incoming_headers = {"authorization": "Bearer client123", "x-custom": "value"}
        result = provider._prepare_proxy_headers("provider_token", incoming_headers)

        # Client authorization should be removed and replaced with provider token
        assert result.get("authorization") != "Bearer client123"
        # Provider token should be present (via _get_headers)
        assert "authorization" in result
        assert result["authorization"] == "Bearer provider_token"
        # Custom header should survive
        assert result.get("x-custom") == "value"


# ---------------------------------------------------------------------------
# Metrics endpoint auth
# ---------------------------------------------------------------------------


class TestMetricsEndpointAuth:
    """Tests for /metrics endpoint authentication."""

    def test_metrics_endpoint_requires_valid_token(self) -> None:
        """SEC-SAN-06: GET /metrics with invalid token → 403."""
        from src.services.gateway.gateway_service import create_app

        accessor = MagicMock()
        accessor.get_enabled_providers.return_value = {}
        accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
        accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=10)
        accessor.get_metrics_config.return_value = MagicMock(
            enabled=True, access_token="correct_metrics_token"
        )

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new_callable=AsyncMock,
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new_callable=AsyncMock,
            ),
            patch("src.services.gateway.gateway_service.DatabaseManager") as MockDB,
            patch("src.services.gateway.gateway_service.GatewayCache") as MockCache,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory"
            ) as MockFactory,
        ):
            mock_cache = MagicMock()
            mock_cache.populate_caches = AsyncMock()
            MockCache.return_value = mock_cache
            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db
            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            MockFactory.return_value = mock_factory

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.get(
                    "/metrics",
                    headers={"Authorization": "Bearer wrong_token"},
                )
                assert response.status_code == 403

    def test_metrics_endpoint_returns_404_when_disabled(self) -> None:
        """SEC-SAN-07: GET /metrics when disabled → 404."""
        from src.services.gateway.gateway_service import create_app

        accessor = MagicMock()
        accessor.get_enabled_providers.return_value = {}
        accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
        accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=10)
        accessor.get_metrics_config.return_value = MagicMock(
            enabled=False, access_token="some_token"
        )

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new_callable=AsyncMock,
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new_callable=AsyncMock,
            ),
            patch("src.services.gateway.gateway_service.DatabaseManager") as MockDB,
            patch("src.services.gateway.gateway_service.GatewayCache") as MockCache,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory"
            ) as MockFactory,
        ):
            mock_cache = MagicMock()
            mock_cache.populate_caches = AsyncMock()
            MockCache.return_value = mock_cache
            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db
            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            MockFactory.return_value = mock_factory

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.get(
                    "/metrics",
                    headers={"Authorization": "Bearer some_token"},
                )
                assert response.status_code == 404
