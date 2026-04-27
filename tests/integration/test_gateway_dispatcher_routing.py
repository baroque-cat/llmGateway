import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.schemas import (
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import DebugMode, StreamingMode


def create_mock_provider_config(
    *,
    provider_type: str = "openai_like",
    models: dict[str, ModelInfo] | None = None,
    streaming_mode: StreamingMode = StreamingMode.AUTO,
    debug_mode: DebugMode = DebugMode.DISABLED,
    retry_enabled: bool = False,
    retry_on_key_error: RetryOnErrorConfig | None = None,
    retry_on_server_error: RetryOnErrorConfig | None = None,
) -> ProviderConfig:
    """Helper to create a ProviderConfig with specified settings."""
    if models is None:
        models = {"gpt-4": ModelInfo()}
    config = ProviderConfig(provider_type=provider_type, keys_path="keys/test/")
    config.enabled = True
    config.models = models
    config.gateway_policy = GatewayPolicyConfig()
    config.gateway_policy.streaming_mode = streaming_mode.value  # expects string
    config.gateway_policy.debug_mode = debug_mode.value
    config.gateway_policy.retry = RetryPolicyConfig(enabled=retry_enabled)
    if retry_on_key_error:
        config.gateway_policy.retry.on_key_error = retry_on_key_error
    if retry_on_server_error:
        config.gateway_policy.retry.on_server_error = retry_on_server_error
    return config


@pytest.fixture
def mock_accessor():
    """Create a mock ConfigAccessor with basic provider configuration."""
    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    return accessor


@pytest.mark.asyncio
async def test_gateway_dispatcher_routing_debug_mode():
    """
    Integration test: verify that catch_all_endpoint routes to the correct handler
    based on provider configuration (debug mode).
    When debug mode is enabled, the request should be routed to _handle_buffered_request.
    """
    from src.services.gateway_service import create_app

    # Create a mock accessor with debug mode enabled
    accessor = MagicMock()
    provider_config = create_mock_provider_config(debug_mode=DebugMode.NO_CONTENT)
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    # Mock database initialization to avoid real DB calls
    with (
        patch(
            "src.services.gateway_service.database.init_db_pool", new_callable=AsyncMock
        ) as mock_init_db,  # noqa: F841
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ) as mock_close_db,  # noqa: F841
        patch("src.services.gateway_service.DatabaseManager") as MockDatabaseManager,
        patch(
            "src.services.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway_service.GatewayCache") as MockGatewayCache,
        patch("src.services.gateway_service._get_token_from_headers") as mock_get_token,
        patch("src.services.gateway_service.get_provider") as mock_get_provider,
    ):
        # Setup mock instances
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        # Mock token extraction
        mock_get_token.return_value = "valid_token"

        # Mock provider
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        # Create the app with mocked dependencies
        app = create_app(accessor)

        # Patch the handlers to track which one is called
        with (
            patch(
                "src.services.gateway_service._handle_buffered_request"
            ) as mock_buffered_handler,
            patch(
                "src.services.gateway_service._handle_buffered_retryable_request"
            ) as mock_retry_handler,
            patch(
                "src.services.gateway_service._handle_full_stream_request"
            ) as mock_full_stream_handler,
        ):
            # Set return values for handlers
            from fastapi.responses import JSONResponse

            mock_response = JSONResponse(content={"test": "debug"})
            mock_buffered_handler.return_value = mock_response
            mock_retry_handler.return_value = mock_response
            mock_full_stream_handler.return_value = mock_response

            # Use TestClient to simulate request
            with TestClient(app) as client:
                response = client.post(  # noqa: F841
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer valid_token"},
                    json={"model": "gpt-4", "messages": []},
                )

            # Assert that the correct handler was called
            # With debug mode enabled, should route to _handle_buffered_request
            assert mock_buffered_handler.called
            assert not mock_retry_handler.called
            assert not mock_full_stream_handler.called

            # Verify the handler was called with correct arguments
            mock_buffered_handler.assert_called_once()
            # Ensure the call includes the request, provider, and instance_name
            call_args = mock_buffered_handler.call_args
            assert call_args[0][0]  # request object
            assert call_args[0][1] == mock_provider
            assert call_args[0][2] == "test_instance"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_config_kwargs, expected_handler_name",
    [
        # Debug mode enabled -> _handle_buffered_request
        (
            {"debug_mode": DebugMode.NO_CONTENT},
            "_handle_buffered_request",
        ),
        (
            {"debug_mode": DebugMode.FULL_BODY},
            "_handle_buffered_request",
        ),
        # Retry enabled -> _handle_buffered_retryable_request
        (
            {"retry_enabled": True},
            "_handle_buffered_retryable_request",
        ),
        # Single model instance -> _handle_full_stream_request
        (
            {"models": {"gpt-4": ModelInfo()}},
            "_handle_full_stream_request",
        ),
        # Gemini provider -> _handle_full_stream_request
        (
            {"provider_type": "gemini"},
            "_handle_full_stream_request",
        ),
        # Streaming mode disabled -> _handle_buffered_request (partial stream)
        (
            {"streaming_mode": StreamingMode.DISABLED},
            "_handle_buffered_request",
        ),
        # Default case (multi-model, non-gemini, no debug, no retry) -> _handle_buffered_request
        (
            {"models": {"gpt-4": ModelInfo(), "gpt-3.5-turbo": ModelInfo()}},
            "_handle_buffered_request",
        ),
    ],
)
async def test_gateway_dispatcher_routing(
    provider_config_kwargs, expected_handler_name
):
    """
    Parameterized integration test verifying catch_all_endpoint routes to the correct handler
    based on provider configuration.
    """
    from src.services.gateway_service import create_app

    # Create a mock accessor with the specified provider config
    accessor = MagicMock()
    provider_config = create_mock_provider_config(**provider_config_kwargs)
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    # Mock database initialization and other dependencies
    with (
        patch(
            "src.services.gateway_service.database.init_db_pool", new_callable=AsyncMock
        ) as mock_init_db,  # noqa: F841
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ) as mock_close_db,  # noqa: F841
        patch("src.services.gateway_service.DatabaseManager") as MockDatabaseManager,
        patch(
            "src.services.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway_service.GatewayCache") as MockGatewayCache,
        patch("src.services.gateway_service._get_token_from_headers") as mock_get_token,
        patch("src.services.gateway_service.get_provider") as mock_get_provider,
    ):
        # Setup mock instances
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        # Mock token extraction
        mock_get_token.return_value = "valid_token"

        # Mock provider
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        # Create the app with mocked dependencies
        app = create_app(accessor)

        # Patch the handlers to track which one is called
        with (
            patch(
                "src.services.gateway_service._handle_buffered_request"
            ) as mock_buffered_handler,
            patch(
                "src.services.gateway_service._handle_buffered_retryable_request"
            ) as mock_retry_handler,
            patch(
                "src.services.gateway_service._handle_full_stream_request"
            ) as mock_full_stream_handler,
        ):
            # Set return values for handlers
            from fastapi.responses import JSONResponse

            mock_response = JSONResponse(content={"test": "routing"})
            mock_buffered_handler.return_value = mock_response
            mock_retry_handler.return_value = mock_response
            mock_full_stream_handler.return_value = mock_response

            # Use TestClient to simulate request
            with TestClient(app) as client:
                response = client.post(  # noqa: F841
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer valid_token"},
                    json={"model": "gpt-4", "messages": []},
                )

            # Determine which handler should have been called
            if expected_handler_name == "_handle_buffered_request":
                assert mock_buffered_handler.called
                assert not mock_retry_handler.called
                assert not mock_full_stream_handler.called
                mock_buffered_handler.assert_called_once()
            elif expected_handler_name == "_handle_buffered_retryable_request":
                assert not mock_buffered_handler.called
                assert mock_retry_handler.called
                assert not mock_full_stream_handler.called
                mock_retry_handler.assert_called_once()
            elif expected_handler_name == "_handle_full_stream_request":
                assert not mock_buffered_handler.called
                assert not mock_retry_handler.called
                assert mock_full_stream_handler.called
                mock_full_stream_handler.assert_called_once()
            else:
                pytest.fail(f"Unknown expected handler: {expected_handler_name}")


@pytest.mark.asyncio
async def test_gateway_dispatcher_routing_full_body_regression():
    """
    Regression test: verify that DebugMode.FULL_BODY still routes to
    _handle_buffered_request (not retry or full-stream handlers).
    """
    from src.services.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config(debug_mode=DebugMode.FULL_BODY)
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    with (
        patch(
            "src.services.gateway_service.database.init_db_pool", new_callable=AsyncMock
        ),
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch("src.services.gateway_service.DatabaseManager") as MockDatabaseManager,
        patch(
            "src.services.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway_service.GatewayCache") as MockGatewayCache,
        patch("src.services.gateway_service._get_token_from_headers") as mock_get_token,
        patch("src.services.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        with (
            patch(
                "src.services.gateway_service._handle_buffered_request"
            ) as mock_buffered_handler,
            patch(
                "src.services.gateway_service._handle_buffered_retryable_request"
            ) as mock_retry_handler,
            patch(
                "src.services.gateway_service._handle_full_stream_request"
            ) as mock_full_stream_handler,
        ):
            from fastapi.responses import JSONResponse

            mock_response = JSONResponse(content={"test": "full_body_regression"})
            mock_buffered_handler.return_value = mock_response
            mock_retry_handler.return_value = mock_response
            mock_full_stream_handler.return_value = mock_response

            with TestClient(app) as client:
                client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer valid_token"},
                    json={"model": "gpt-4", "messages": []},
                )

            assert mock_buffered_handler.called
            assert not mock_retry_handler.called
            assert not mock_full_stream_handler.called


@pytest.mark.asyncio
async def test_debug_mode_forces_buffered_response_no_streaming():
    """
    When debug_mode is "no_content" and upstream returns text/event-stream,
    the gateway must call aread() (not StreamMonitor) and return a non-streaming
    Response. Debug mode forces buffered response regardless of content-type.
    """
    from src.services.gateway_service import (
        _debug_and_respond,
    )

    # Build a mock upstream response with SSE content-type
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.headers = httpx.Headers(
        {"content-type": "text/event-stream", "x-request-id": "req-123"}
    )
    upstream_response.aread = AsyncMock(return_value=b'data: {"choices": []}\n\n')
    upstream_response.aclose = AsyncMock()

    # Build a mock request with debug_mode_map set to "no_content"
    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.__str__ = lambda self: "http://test/v1/chat/completions"
    request.headers = {
        "authorization": "Bearer test-token",
        "content-type": "application/json",
    }

    state = MagicMock()
    state.debug_mode_map = {"test_instance": "no_content"}
    request.app.state = state

    request_body = (
        b'{"model": "gpt-4", "messages": [{"role": "user", "content": "hello"}]}'
    )

    # Call _debug_and_respond directly
    response = await _debug_and_respond(
        upstream_response=upstream_response,
        debug_mode="no_content",
        instance_name="test_instance",
        provider_type="openai_like",
        request=request,
        request_body=request_body,
    )

    # Verify aread() was called (not StreamMonitor)
    assert upstream_response.aread.called
    # Verify aclose() was called
    assert upstream_response.aclose.called
    # Verify response is a plain Response (not StreamingResponse)
    from starlette.responses import Response as StarletteResponse
    from starlette.responses import StreamingResponse

    assert isinstance(response, StarletteResponse)
    assert not isinstance(response, StreamingResponse)
    # Verify the response body contains the upstream data
    assert response.body == b'data: {"choices": []}\n\n'
    assert response.status_code == 200


if __name__ == "__main__":
    asyncio.run(test_gateway_dispatcher_routing_debug_mode())
