#!/usr/bin/env python3

"""
Security tests for gateway authentication.

Verifies that:
- Requests without Authorization header are rejected (401)
- Requests with invalid tokens are rejected (401)
- Requests with valid tokens proceed (not 401)
- Requests with malformed Authorization headers are rejected (401)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from src.config.schemas import ModelInfo, ProviderConfig
from src.core.constants import DebugMode, StreamingMode
from src.core.models import CheckResult


def _create_mock_accessor(
    *,
    gateway_access_token: str = "valid_test_token",
) -> MagicMock:
    """Create a mock ConfigAccessor with a single provider instance."""
    accessor = MagicMock()

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.enabled = True
    provider_config.models = {"gpt-4": ModelInfo()}
    provider_config.gateway_policy = MagicMock()
    provider_config.gateway_policy.streaming_mode = StreamingMode.AUTO.value
    provider_config.gateway_policy.debug_mode = DebugMode.DISABLED.value
    provider_config.gateway_policy.retry = MagicMock(enabled=False)
    provider_config.access_control = MagicMock(
        gateway_access_token=gateway_access_token
    )

    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_metrics_config.return_value = MagicMock(enabled=False)
    accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=10)

    return accessor


class TestGatewayAuth:
    """Tests for gateway request authentication."""

    def test_request_without_token_returns_401(self) -> None:
        """SEC-AUTH-01: Request without Authorization header → 401."""
        from src.services.gateway.gateway_service import create_app

        accessor = _create_mock_accessor()

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
            mock_cache.get_instance_name_by_token = MagicMock(return_value=None)
            MockCache.return_value = mock_cache

            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db

            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            MockFactory.return_value = mock_factory

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                assert response.status_code == 401
                assert (
                    "Missing or invalid authentication token"
                    in response.json()["error"]
                )

    def test_request_with_invalid_token_returns_401(self) -> None:
        """SEC-AUTH-02: Request with invalid Bearer token → 401."""
        from src.services.gateway.gateway_service import create_app

        accessor = _create_mock_accessor()

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
            # Invalid token → cache returns None for instance name
            mock_cache.get_instance_name_by_token = MagicMock(return_value=None)
            MockCache.return_value = mock_cache

            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db

            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            MockFactory.return_value = mock_factory

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer wrong_token"},
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                assert response.status_code == 401
                assert "Invalid authentication token" in response.json()["error"]

    def test_request_with_valid_token_proceeds(self) -> None:
        """SEC-AUTH-03: Request with valid Bearer token → not 401 (request is processed)."""
        from src.services.gateway.gateway_service import create_app

        accessor = _create_mock_accessor()

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
            patch(
                "src.services.gateway.gateway_service.get_provider"
            ) as mock_get_provider,
        ):
            mock_cache = MagicMock()
            mock_cache.populate_caches = AsyncMock()
            mock_cache.get_instance_name_by_token = MagicMock(
                side_effect=lambda token: (
                    "test_instance" if token == "valid_test_token" else None
                )
            )
            mock_cache.get_key_from_pool = MagicMock(return_value=(1, "sk-xxx"))
            MockCache.return_value = mock_cache

            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db

            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            mock_http_client = AsyncMock(spec=httpx.AsyncClient)
            mock_factory.get_client_for_provider = AsyncMock(
                return_value=mock_http_client
            )
            MockFactory.return_value = mock_factory

            # Mock provider
            mock_provider = MagicMock()
            mock_provider.parse_request_details = AsyncMock(
                return_value=MagicMock(model_name="gpt-4")
            )
            mock_httpx_response = AsyncMock(spec=httpx.Response)
            mock_httpx_response.status_code = 200
            mock_httpx_response.reason_phrase = "OK"
            mock_httpx_response.headers = {"content-type": "application/json"}

            async def chunk_iter():
                yield b'{"choices": []}'

            mock_httpx_response.aiter_bytes.return_value = chunk_iter()
            mock_httpx_response.aclose = AsyncMock()
            mock_provider.proxy_request = AsyncMock(
                return_value=(
                    mock_httpx_response,
                    CheckResult.success(),
                    b'{"choices": []}',
                )
            )
            mock_get_provider.return_value = mock_provider

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer valid_test_token"},
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                # Should NOT be 401 — request proceeds past auth
                assert response.status_code != 401

    def test_request_with_malformed_authorization_header_returns_401(self) -> None:
        """SEC-AUTH-04: Request with malformed Authorization header → 401."""
        from src.services.gateway.gateway_service import create_app

        accessor = _create_mock_accessor()

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
            mock_cache.get_instance_name_by_token = MagicMock(return_value=None)
            MockCache.return_value = mock_cache

            mock_db = MagicMock()
            mock_db.wait_for_schema_ready = AsyncMock()
            MockDB.return_value = mock_db

            mock_factory = MagicMock()
            mock_factory.close_all = AsyncMock()
            MockFactory.return_value = mock_factory

            app = create_app(accessor)

            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "weird_format"},
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                assert response.status_code == 401
