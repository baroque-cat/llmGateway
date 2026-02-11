"""
End-to-end test for gateway request logging.
Verifies that the gateway logs requests in the new unified format.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.schemas import ModelInfo, ProviderConfig
from src.core.constants import DebugMode, StreamingMode
from src.core.models import CheckResult


def create_mock_provider_config(
    *,
    provider_type: str = "openai_like",
    models: dict[str, ModelInfo] | None = None,
    streaming_mode: StreamingMode = StreamingMode.AUTO,
    debug_mode: DebugMode = DebugMode.DISABLED,
) -> ProviderConfig:
    """Helper to create a ProviderConfig with specified settings."""
    if models is None:
        models = {"gpt-4": ModelInfo()}
    config = ProviderConfig()
    config.provider_type = provider_type
    config.enabled = True
    config.models = models
    config.gateway_policy = MagicMock()
    config.gateway_policy.streaming_mode = streaming_mode.value
    config.gateway_policy.debug_mode = debug_mode.value
    config.gateway_policy.retry = MagicMock(enabled=False)
    config.access_control = MagicMock(gateway_access_token="test_token")
    return config


@pytest.mark.asyncio
async def test_gateway_request_logging():
    """
    E2E test: make a request to the gateway and verify the GATEWAY_ACCESS log format.
    """
    from src.services.gateway_service import create_app

    # Create a mock accessor with a single provider instance
    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_metrics_config.return_value = MagicMock(enabled=False)

    # Mock database initialization
    with (
        patch(
            "src.services.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ) as mock_init_db,
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ) as mock_close_db,
        patch("src.services.gateway_service.DatabaseManager") as MockDatabaseManager,
        patch("src.services.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway_service.get_provider") as mock_get_provider,
        patch("src.services.gateway_service.logger") as mock_logger,
    ):
        # Mock cache behavior
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "sk-xxx")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        # Mock database manager
        mock_db_manager = MagicMock()
        MockDatabaseManager.return_value = mock_db_manager

        # Mock HTTP client factory
        mock_http_factory = MagicMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_http_factory.get_client_for_provider = AsyncMock(return_value=mock_client)
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory

        # Mock provider
        mock_provider = MagicMock()
        mock_provider.parse_request_details = AsyncMock(
            return_value=MagicMock(model_name="gpt-4")
        )
        # Simulate a successful streaming response
        mock_httpx_response = AsyncMock(spec=httpx.Response)
        mock_httpx_response.status_code = 200
        mock_httpx_response.reason_phrase = "OK"
        mock_httpx_response.headers = {"content-type": "application/json"}

        # Create a simple async iterator for response body
        async def chunk_iterator():
            yield b'{"choices": []}'

        mock_httpx_response.aiter_bytes.return_value = chunk_iterator()
        mock_httpx_response.aclose = AsyncMock()
        mock_provider.proxy_request = AsyncMock(
            return_value=(mock_httpx_response, CheckResult.success())
        )
        mock_get_provider.return_value = mock_provider

        # Create the FastAPI app with mocked dependencies
        app = create_app(accessor)
        # The lifespan startup will have set app.state attributes; we need to ensure they exist
        # Since we mocked the classes, the startup will assign our mocks.
        # However we must also set the dispatcher state attributes that are computed in startup.
        # Let's set them directly after app creation (the lifespan hasn't run yet because
        # TestClient doesn't trigger lifespan? Actually it does via lifespan context manager.
        # We'll rely on the startup logic but we need to mock the computed sets.
        # We'll patch the app.state attributes after startup, but easier: we can set them now.
        # The catch_all_endpoint expects these attributes; we'll set them.

        with TestClient(app) as client:
            # Make a request with the valid token
            response = client.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": "Bearer test_token",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "test"}],
                },
            )
            # The response should be streaming; we need to read it
            assert response.status_code == 200
            # Consume the response body to trigger streaming completion
            response.content

        # Verify that the GATEWAY_ACCESS log was emitted
        mock_logger.info.assert_called()
        # Find the call containing GATEWAY_ACCESS
        gateway_access_call = None
        for call in mock_logger.info.call_args_list:
            if "GATEWAY_ACCESS" in call[0][0]:
                gateway_access_call = call
                break
        assert gateway_access_call is not None, "GATEWAY_ACCESS log not found"
        log_message = gateway_access_call[0][0]
        # Check format components
        assert "GATEWAY_ACCESS |" in log_message
        assert "->" in log_message
        assert "test_instance:gpt-4" in log_message
        assert "200 OK -> VALID" in log_message
        # Ensure duration is logged (contains 's)')
        assert "s)" in log_message

        # Verify that the lifespan startup ran
        startup_log_calls = [
            call
            for call in mock_logger.info.call_args_list
            if "Gateway service starting up" in call[0][0]
        ]
        assert len(startup_log_calls) == 1, "Lifespan startup log not found"

        # Cleanup
        mock_init_db.assert_called_once()
        mock_close_db.assert_called_once()
