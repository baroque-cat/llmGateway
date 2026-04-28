import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from src.config.schemas import (
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import DebugMode, ErrorReason, StreamingMode
from src.core.models import CheckResult, RequestDetails


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


@pytest.mark.asyncio
async def test_gateway_routes_to_full_stream_handler_when_auto_with_eligible_provider():
    """
    Integration test: verify that catch_all_endpoint routes to the existing
    `_handle_full_stream_request` handler when a single-model provider
    is configured with streaming_mode = StreamingMode.AUTO (and no retry policy).

    This test verifies that true full-duplex streaming is triggered automatically
    for eligible provider configurations, where request bodies are streamed directly
    without buffering.
    """
    from src.services.gateway_service import create_app

    # Create a mock accessor with a single-model provider and auto streaming mode
    accessor = MagicMock()
    # Create a config with single model, streaming_mode=AUTO
    provider_config = create_mock_provider_config(
        models={"gpt-4": ModelInfo()},  # single model
        streaming_mode=StreamingMode.AUTO,  # placeholder
    )

    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    # Mock database initialization to avoid real DB calls
    with (
        patch(
            "src.services.gateway_service.database.init_db_pool", new_callable=AsyncMock
        ) as _mock_init_db,
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ) as _mock_close_db,
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
        mock_client = MagicMock()
        mock_http_factory.get_client_for_provider = AsyncMock(return_value=mock_client)
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
        # Mock proxy_request to capture content argument and simulate success
        mock_provider.proxy_request = AsyncMock()
        # Create a mock httpx.Response that satisfies the handler
        mock_upstream_response = MagicMock(spec=httpx.Response)
        mock_upstream_response.status_code = 200
        mock_upstream_response.headers = {"content-type": "application/json"}

        # Mock async iterator for streaming response body
        async def empty_aiter_bytes():
            yield b""

        mock_upstream_response.aiter_bytes = MagicMock(return_value=empty_aiter_bytes())
        mock_upstream_response.aclose = AsyncMock()
        # Create a successful CheckResult
        successful_result = CheckResult.success()
        mock_provider.proxy_request.return_value = (
            mock_upstream_response,
            successful_result,
        )

        # Create the app with mocked dependencies
        app = create_app(accessor)

        # Patch buffered handlers to verify they are not called
        with (
            patch(
                "src.services.gateway_service._handle_buffered_request"
            ) as mock_buffered_handler,
            patch(
                "src.services.gateway_service._handle_buffered_retryable_request"
            ) as mock_retry_handler,
        ):
            # Set return values for buffered handlers (they shouldn't be called)
            from fastapi.responses import JSONResponse

            mock_response = JSONResponse(content={"test": "streaming"})
            mock_buffered_handler.return_value = mock_response
            mock_retry_handler.return_value = mock_response

            # Use TestClient to simulate request
            with TestClient(app) as client:
                _ = client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer valid_token"},
                    json={"model": "gpt-4", "messages": []},
                )

            # Verify that buffered handlers were NOT called
            assert not mock_buffered_handler.called
            assert not mock_retry_handler.called

            # Verify that provider.proxy_request was called exactly once
            mock_provider.proxy_request.assert_called_once()
            # Extract the content argument
            call_args = mock_provider.proxy_request.call_args
            # content is the 7th positional argument (or keyword 'content')
            if "content" in call_args.kwargs:
                content_arg = call_args.kwargs["content"]
            else:
                content_arg = call_args.args[
                    6
                ]  # 0: client, 1: token, 2: method, 3: headers, 4: path, 5: query_params, 6: content
            # Assert that content is not bytes (should be an async generator)
            assert not isinstance(
                content_arg, bytes
            ), "Request body should be streamed, not buffered as bytes"
            # Assert it's an async generator (should be from request.stream())
            assert isinstance(
                content_arg, AsyncGenerator
            ), "Content should be an async generator"


@pytest.mark.asyncio
async def test_gateway_routes_to_full_stream_handler_for_gemini_provider():
    """
    Integration test: verify that catch_all_endpoint routes to the existing
    `_handle_full_stream_request` handler when a provider is configured with
    provider_type = "gemini" (and no retry policy, no debug mode).

    This test verifies that true full-duplex streaming is triggered automatically
    for Gemini provider configurations, where request bodies are streamed directly
    without buffering, and the model is parsed from the URL path.
    """
    from src.services.gateway_service import create_app

    # Create a mock accessor with a Gemini provider and auto streaming mode
    accessor = MagicMock()
    # Create a config with multiple models, streaming_mode=AUTO, provider_type=gemini
    provider_config = create_mock_provider_config(
        provider_type="gemini",
        models={
            "gemini-2.5-pro": ModelInfo(),
            "gemini-2.0-flash": ModelInfo(),
        },  # multiple models, Gemini can parse from URL
        streaming_mode=StreamingMode.AUTO,
    )

    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    # Mock database initialization to avoid real DB calls
    with (
        patch(
            "src.services.gateway_service.database.init_db_pool", new_callable=AsyncMock
        ) as _mock_init_db,
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ) as _mock_close_db,
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
        mock_client = MagicMock()
        mock_http_factory.get_client_for_provider = AsyncMock(return_value=mock_client)
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
        # Mock proxy_request to capture content argument and simulate success
        mock_provider.proxy_request = AsyncMock()

        # Mock parse_request_details for Gemini provider
        async def parse_details_side_effect(
            path: str, content: bytes
        ) -> RequestDetails:
            return RequestDetails(model_name="gemini-2.5-pro")

        mock_provider.parse_request_details = AsyncMock(
            side_effect=parse_details_side_effect
        )
        # Create a mock httpx.Response that satisfies the handler
        mock_upstream_response = MagicMock(spec=httpx.Response)
        mock_upstream_response.status_code = 200
        mock_upstream_response.headers = {"content-type": "application/json"}

        # Mock async iterator for streaming response body
        async def empty_aiter_bytes():
            yield b""

        mock_upstream_response.aiter_bytes = MagicMock(return_value=empty_aiter_bytes())
        mock_upstream_response.aclose = AsyncMock()
        # Create a successful CheckResult
        successful_result = CheckResult.success()
        mock_provider.proxy_request.return_value = (
            mock_upstream_response,
            successful_result,
        )

        # Create the app with mocked dependencies
        app = create_app(accessor)

        # Patch buffered handlers to verify they are not called
        with (
            patch(
                "src.services.gateway_service._handle_buffered_request"
            ) as mock_buffered_handler,
            patch(
                "src.services.gateway_service._handle_buffered_retryable_request"
            ) as mock_retry_handler,
        ):
            # Set return values for buffered handlers (they shouldn't be called)
            from fastapi.responses import JSONResponse

            mock_response = JSONResponse(content={"test": "streaming"})
            mock_buffered_handler.return_value = mock_response
            mock_retry_handler.return_value = mock_response

            # Use TestClient to simulate request
            with TestClient(app) as client:
                # Gemini-style path with model name embedded
                _ = client.post(
                    "/v1beta/models/gemini-2.5-pro:generateContent",
                    headers={"Authorization": "Bearer valid_token"},
                    json={"model": "gemini-2.5-pro", "messages": []},
                )

            # Verify that buffered handlers were NOT called
            assert not mock_buffered_handler.called
            assert not mock_retry_handler.called

            # Verify that provider.proxy_request was called exactly once
            mock_provider.proxy_request.assert_called_once()
            # Extract the content argument
            call_args = mock_provider.proxy_request.call_args
            # content is the 7th positional argument (or keyword 'content')
            if "content" in call_args.kwargs:
                content_arg = call_args.kwargs["content"]
            else:
                content_arg = call_args.args[
                    6
                ]  # 0: client, 1: token, 2: method, 3: headers, 4: path, 5: query_params, 6: content
            # Assert that content is not bytes (should be an async generator)
            assert not isinstance(
                content_arg, bytes
            ), "Request body should be streamed, not buffered as bytes"
            # Assert it's an async generator (should be from request.stream())
            assert isinstance(
                content_arg, AsyncGenerator
            ), "Content should be an async generator"
            # Verify parse_request_details was called with correct path

            mock_provider.parse_request_details.assert_called_once()
            parse_args = mock_provider.parse_request_details.call_args
            # Should be called with path and empty bytes (since gemini can parse from URL)
            assert (
                parse_args.kwargs["path"]
                == "/v1beta/models/gemini-2.5-pro:generateContent"
            )
            assert parse_args.kwargs["content"] == b""


@pytest.mark.asyncio
async def test_gateway_full_stream_read_error_converted_to_gateway_stream_error():
    """
    6.2 (full duplex context): When aiter_bytes() raises httpx.ReadError during
    full-duplex streaming, StreamMonitor catches it and raises GatewayStreamError
    with provider_name and model_name context.

    This test directly calls _handle_full_stream_request to verify that:
    1. The handler returns StreamingResponse for successful proxy_request
    2. When iterating the stream, httpx.ReadError is converted to GatewayStreamError
    3. GatewayStreamError carries provider_name and model_name
    4. The raw httpx.ReadError does NOT reach the caller directly
    """
    from src.services.gateway_service import (
        GatewayStreamError,
        _handle_full_stream_request,
    )

    # Create a mock request with all necessary state
    req = MagicMock(spec=Request)
    req.url.path = "/v1/chat/completions"
    req.url.query = ""
    req.method = "POST"
    req.headers = {"authorization": "Bearer test-token"}
    req.body = AsyncMock(return_value=b'{"model": "gpt-4"}')
    req.client = MagicMock()
    req.client.host = "127.0.0.1"

    # Create state mock
    state = MagicMock()
    state.gateway_cache = MagicMock()
    state.gateway_cache.get_key_from_pool = MagicMock(return_value=(1, "fake_api_key"))
    state.gateway_cache.remove_key_from_pool = AsyncMock()
    state.http_client_factory = MagicMock()
    state.http_client_factory.get_client_for_provider = AsyncMock(
        return_value=MagicMock()
    )
    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()
    state.accessor = MagicMock()
    state.debug_mode_map = {}

    req.app.state = state

    # Mock provider
    provider = MagicMock()
    instance_name = "test_instance"
    model_name = "gpt-4"

    # Create mock upstream response with aiter_bytes() that raises ReadError
    mock_upstream_response = MagicMock(spec=httpx.Response)
    mock_upstream_response.status_code = 200
    mock_upstream_response.reason_phrase = "OK"
    mock_upstream_response.headers = {"content-type": "application/json"}

    async def read_error_iterator():
        yield b"partial_chunk"
        raise httpx.ReadError("Connection lost during streaming")

    mock_upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    mock_upstream_response.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(mock_upstream_response, CheckResult.success())
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Handler returns StreamingResponse
    assert isinstance(response, StreamingResponse)

    # Iterating the stream raises GatewayStreamError (not httpx.ReadError)
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # Verify GatewayStreamError attributes
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == model_name
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT

    # Verify that httpx.ReadError was intercepted (not raised directly)
    assert not isinstance(exc_info.value, httpx.ReadError)


if __name__ == "__main__":
    asyncio.run(
        test_gateway_routes_to_full_stream_handler_when_auto_with_eligible_provider()
    )
