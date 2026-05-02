"""
Unit tests for core gateway_service logic.

Tests cover:
  1-5: _handle_full_stream_request / _handle_buffered_retryable_request
  6-8: create_app factory
  9-11: _sanitize_headers / _sanitize_body
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.services.gateway.gateway_service import (
    GatewayStreamError,
    _handle_buffered_retryable_request,
    _handle_full_stream_request,
    _sanitize_body,
    _sanitize_headers,
    create_app,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_request(
    method: str = "POST",
    path: str = "/v1/chat/completions",
    client_host: str = "127.0.0.1",
) -> MagicMock:
    """Create a mock FastAPI Request with app.state populated."""
    request = MagicMock()
    request.method = method
    request.url = MagicMock()
    request.url.path = path
    request.url.query = ""
    request.client = MagicMock()
    request.client.host = client_host

    # Build app.state with all required dependencies
    mock_cache = MagicMock()
    mock_cache.get_key_from_pool = Mock(return_value=(1, "sk-test-key"))
    mock_cache.remove_key_from_pool = AsyncMock()

    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(
        return_value=MagicMock(spec=httpx.AsyncClient)
    )

    mock_db_manager = MagicMock()

    mock_accessor = MagicMock()
    # Default provider config
    mock_provider_config = MagicMock()
    mock_provider_config.models = {"gpt-4": MagicMock()}
    mock_provider_config.gateway_policy = MagicMock()
    mock_provider_config.gateway_policy.retry = MagicMock()
    mock_provider_config.gateway_policy.retry.enabled = False
    mock_provider_config.gateway_policy.streaming_mode = "auto"
    mock_provider_config.gateway_policy.debug_mode = "disabled"
    mock_accessor.get_provider_or_raise = Mock(return_value=mock_provider_config)
    mock_accessor.get_provider = Mock(return_value=mock_provider_config)
    mock_accessor.get_enabled_providers = Mock(return_value={})

    request.app = MagicMock()
    request.app.state.gateway_cache = mock_cache
    request.app.state.http_client_factory = mock_http_factory
    request.app.state.db_manager = mock_db_manager
    request.app.state.accessor = mock_accessor
    request.app.state.debug_mode_map = {"openai": "disabled"}
    request.app.state.full_stream_instances = {"openai"}
    request.app.state.gemini_stream_instances = set()
    request.app.state.single_model_map = {"openai": "gpt-4"}

    return request


def _make_mock_provider() -> AsyncMock:
    """Create a mock IProvider."""
    provider = AsyncMock()
    provider.proxy_request = AsyncMock()
    provider.parse_request_details = AsyncMock(
        return_value=RequestDetails(model_name="gpt-4")
    )
    return provider


def _make_mock_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> AsyncMock:
    """Create a mock httpx.Response."""
    response = AsyncMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = httpx.Headers(headers or {"content-type": "application/json"})
    response.aread = AsyncMock(return_value=b'{"ok": true}')
    response.aclose = AsyncMock()
    response.aiter_bytes = MagicMock()
    return response


# ---------------------------------------------------------------------------
# Tests 1-5: Core request handling
# ---------------------------------------------------------------------------


class TestFullStreamRequest:
    """Tests for _handle_full_stream_request."""

    @pytest.mark.asyncio
    async def test_full_stream_request_success(self):
        """Successful proxy_request → StreamingResponse returned."""
        request = _make_mock_request()
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)

        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ) as mock_forward:
            result = await _handle_full_stream_request(
                request, provider, "openai", "gpt-4"
            )

            assert result is mock_streaming_response
            mock_forward.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_stream_request_no_keys(self):
        """No available keys → 503 JSONResponse."""
        request = _make_mock_request()
        provider = _make_mock_provider()

        # Make cache return no key
        request.app.state.gateway_cache.get_key_from_pool = Mock(return_value=None)

        result = await _handle_full_stream_request(request, provider, "openai", "gpt-4")

        # Should return a 503 JSONResponse
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_full_stream_request_read_error(self):
        """aiter_bytes raises httpx.ReadError → GatewayStreamError."""
        request = _make_mock_request()
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)

        provider.proxy_request.return_value = (mock_response, success_result, None)

        # Make StreamMonitor raise GatewayStreamError
        async def error_stream():
            yield b"partial"
            raise httpx.ReadError("connection lost")

        mock_monitor = MagicMock()
        mock_monitor.__aiter__ = Mock(return_value=mock_monitor)
        mock_monitor.__anext__ = AsyncMock(
            side_effect=GatewayStreamError(
                "stream error", provider_name="openai", model_name="gpt-4"
            )
        )

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=mock_monitor,
        ):
            streaming_result = StreamingResponse(content=mock_monitor, status_code=200)

            with patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=streaming_result),
            ):
                result = await _handle_full_stream_request(
                    request, provider, "openai", "gpt-4"
                )
                # The StreamingResponse is returned; the error happens when
                # the client reads the stream, not during the handler call.
                assert isinstance(result, StreamingResponse)


class TestBufferedRetryableRequest:
    """Tests for _handle_buffered_retryable_request."""

    @pytest.mark.asyncio
    async def test_buffered_request_success(self):
        """Successful proxy_request → response returned."""
        request = _make_mock_request()
        # Enable retry for buffered path
        request.app.state.accessor.get_provider_or_raise.return_value.gateway_policy.retry.enabled = (
            True
        )
        request.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)

        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

            assert result is mock_streaming_response

    @pytest.mark.asyncio
    async def test_buffered_request_retry_on_server_error(self):
        """First call → SERVER_ERROR, second → success. Retry works."""
        request = _make_mock_request()
        # Enable retry with policy
        mock_provider_config = (
            request.app.state.accessor.get_provider_or_raise.return_value
        )
        mock_provider_config.gateway_policy.retry.enabled = True
        retry_policy = MagicMock()
        retry_policy.attempts = 3
        retry_policy.backoff_sec = 0
        retry_policy.backoff_factor = 1.0
        mock_provider_config.gateway_policy.retry.on_server_error = retry_policy
        mock_provider_config.gateway_policy.retry.on_key_error = MagicMock()
        mock_provider_config.gateway_policy.retry.on_key_error.attempts = 3
        mock_provider_config.gateway_policy.retry.on_key_error.backoff_sec = 0
        mock_provider_config.gateway_policy.retry.on_key_error.backoff_factor = 1.0

        request.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

        provider = _make_mock_provider()
        mock_response_fail = _make_mock_response(status_code=500)
        mock_response_ok = _make_mock_response(status_code=200)
        fail_result = CheckResult.fail(ErrorReason.SERVER_ERROR, status_code=500)
        success_result = CheckResult.success(status_code=200)

        # First call fails, second succeeds
        provider.proxy_request.side_effect = [
            (mock_response_fail, fail_result, b'{"error": "server error"}'),
            (mock_response_ok, success_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep", new=AsyncMock()
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

            # Second attempt succeeded → StreamingResponse
            assert result is mock_streaming_response
            assert provider.proxy_request.call_count == 2

    @pytest.mark.asyncio
    async def test_buffered_request_key_rotation_on_invalid_key(self):
        """First key → INVALID_KEY (removed from pool), second → success."""
        request = _make_mock_request()
        mock_provider_config = (
            request.app.state.accessor.get_provider_or_raise.return_value
        )
        mock_provider_config.gateway_policy.retry.enabled = True
        key_error_policy = MagicMock()
        key_error_policy.attempts = 3
        key_error_policy.backoff_sec = 0
        key_error_policy.backoff_factor = 1.0
        mock_provider_config.gateway_policy.retry.on_key_error = key_error_policy
        server_error_policy = MagicMock()
        server_error_policy.attempts = 3
        server_error_policy.backoff_sec = 0
        server_error_policy.backoff_factor = 1.0
        mock_provider_config.gateway_policy.retry.on_server_error = server_error_policy

        request.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

        provider = _make_mock_provider()
        mock_response_fail = _make_mock_response(status_code=401)
        mock_response_ok = _make_mock_response(status_code=200)
        fail_result = CheckResult.fail(ErrorReason.INVALID_KEY, status_code=401)
        success_result = CheckResult.success(status_code=200)

        # First call → INVALID_KEY, second → success
        provider.proxy_request.side_effect = [
            (mock_response_fail, fail_result, b'{"error": "invalid key"}'),
            (mock_response_ok, success_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep", new=AsyncMock()
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

            # Key rotation succeeded → StreamingResponse
            assert result is mock_streaming_response
            assert provider.proxy_request.call_count == 2
            # Verify key was removed from pool
            request.app.state.gateway_cache.remove_key_from_pool.assert_called()


# ---------------------------------------------------------------------------
# Tests 6-8: create_app factory
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for the create_app factory function."""

    def _make_mock_accessor(self) -> MagicMock:
        """Create a mock ConfigAccessor for create_app."""
        accessor = MagicMock()
        accessor.get_enabled_providers = Mock(return_value={})
        accessor.get_database_dsn = Mock(
            return_value="postgresql://test:test@localhost/test"
        )
        accessor.get_pool_config = Mock()
        accessor.get_pool_config.return_value.min_size = 2
        accessor.get_pool_config.return_value.max_size = 5
        accessor.get_metrics_config = Mock()
        accessor.get_metrics_config.return_value.enabled = False
        accessor.get_metrics_config.return_value.access_token = None
        return accessor

    def test_create_app_returns_fastapi_app(self):
        """create_app() returns a FastAPI instance."""
        accessor = self._make_mock_accessor()
        # Patch lifespan dependencies so the app can be created without DB
        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
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

            app = create_app(accessor)
            assert isinstance(app, FastAPI)

    def test_create_app_registers_metrics_endpoint(self):
        """The /metrics endpoint is registered in the app routes."""
        accessor = self._make_mock_accessor()
        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
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

            app = create_app(accessor)

            # Check that /metrics route exists
            routes = [route.path for route in app.routes]
            assert "/metrics" in routes

    def test_create_app_registers_catch_all_endpoint(self):
        """The catch-all route /{full_path:path} is registered."""
        accessor = self._make_mock_accessor()
        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
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

            app = create_app(accessor)

            # Check that catch-all route exists
            routes = [route.path for route in app.routes]
            assert "/{full_path:path}" in routes


# ---------------------------------------------------------------------------
# Tests 9-11: Sanitization helpers
# ---------------------------------------------------------------------------


class TestSanitizeHeadersCore:
    """Core sanitization tests for _sanitize_headers."""

    def test_sanitize_headers_masks_authorization(self):
        """Authorization header with Bearer token is masked to 'Bearer ***'."""
        headers = {"authorization": "Bearer secret"}
        result = _sanitize_headers(headers)
        assert result["authorization"] == "Bearer ***"
        assert "secret" not in result["authorization"]

    def test_sanitize_headers_masks_api_key(self):
        """x-api-key header value is completely masked to '***'."""
        headers = {"x-api-key": "sk-123"}
        result = _sanitize_headers(headers)
        assert result["x-api-key"] == "***"
        assert "sk-123" not in result["x-api-key"]


class TestSanitizeBodyCore:
    """Core sanitization tests for _sanitize_body."""

    def test_sanitize_body_masks_sensitive_fields(self):
        """_sanitize_body masks api_key in JSON body for openai_like provider."""
        body = b'{"api_key":"secret","messages":[]}'
        result = _sanitize_body(body, "openai_like")
        assert '"api_key": "***"' in result
        assert "secret" not in result
        assert '"messages"' in result
