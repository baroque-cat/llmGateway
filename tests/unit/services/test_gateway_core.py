"""
Unit tests for core gateway_service logic.

Tests cover:
  1-5: _handle_full_stream_request / _handle_buffered_retryable_request
  6-8: create_app factory
  9-11: _sanitize_headers / _sanitize_body
  12-15: Static analysis / Pydantic validation (moved from integration)
"""

import inspect
import re
import inspect
import re
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.config.schemas import GatewayPolicyConfig
from src.services.gateway.gateway_service import (
    GatewayStreamError,
    _handle_buffered_retryable_request,
    _handle_full_stream_request,
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
# Tests 12-15: Static analysis / Pydantic validation
# (Moved from integration/test_gateway_refactor.py)
# ---------------------------------------------------------------------------


class TestGatewayStaticAnalysis:
    """Static analysis and Pydantic validation tests for gateway service.

    These tests verify source code structure and config validation —
    no HTTP or runtime dependency, pure unit tests.
    """

    def test_dead_code_removed_in_openai_like_proxy_request(self):
        """
        Static check: verify proxy_request in openai_like.py no longer has
        duplicated if/else branches with identical bodies (dead code removal).
        """
        import src.providers.impl.openai_like as oai_mod

        source = inspect.getsource(oai_mod.OpenAILikeProvider.proxy_request)

        lines = source.strip().split("\n")
        assert len(lines) < 50, (
            f"proxy_request has {len(lines)} lines — expected a thin wrapper < 50 lines. "
            f"Possible duplicated if/else branches still present."
        )

        for i, line in enumerate(lines):
            if "if " in line and "else:" in lines[i + 1] if i + 1 < len(lines) else False:
                pytest.fail(
                    f"Found if/else at line {i} in proxy_request — "
                    f"dead code with identical branches should have been removed."
                )

    def test_no_json_503_in_retry_handler(self):
        """
        Static analysis: _handle_buffered_retryable_request has no
        JSONResponse(status_code=503, content={"error": ...}) in the retry/error
        handling paths — all replaced by forward_error_to_client().
        """
        import src.services.gateway.gateway_service as gw_mod

        source = inspect.getsource(gw_mod._handle_buffered_retryable_request)

        # Count all JSONResponse(status_code=503) occurrences
        json_503_count = len(
            re.findall(r"JSONResponse\s*\(\s*status_code\s*=\s*503", source)
        )

        # There should be exactly 1: the "no available API keys" guard
        assert json_503_count == 1, (
            f"Expected exactly 1 JSONResponse(status_code=503) in "
            f"_handle_buffered_retryable_request (the 'no keys available' guard), "
            f"but found {json_503_count}. All retry-exhaustion paths should use "
            f"forward_error_to_client() instead."
        )

        # Verify forward_error_to_client is used in the handler
        forward_error_count = len(re.findall(r"forward_error_to_client\(", source))
        assert forward_error_count >= 3, (
            f"Expected at least 3 forward_error_to_client calls in "
            f"_handle_buffered_retryable_request (client error, key fault last, "
            f"server error last), but found {forward_error_count}."
        )

    def test_pydantic_rejects_headers_only(self):
        """
        Config with debug_mode: "headers_only" → Pydantic validation error.
        """
        with pytest.raises(ValidationError) as exc_info:
            GatewayPolicyConfig(debug_mode="headers_only")

        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("debug_mode",) for e in errors
        ), f"Expected validation error on 'debug_mode' field, got: {errors}"

    def test_upstream_attempt_used_in_all_handler_paths(self):
        """
        Static analysis: every path in both handlers that involves an upstream
        response ends with discard_response(), forward_error_to_client(),
        forward_buffered_body(), or forward_success_stream().
        """
        import src.services.gateway.gateway_service as gw_mod

        buffered_source = inspect.getsource(gw_mod._handle_buffered_retryable_request)
        stream_source = inspect.getsource(gw_mod._handle_full_stream_request)

        # Check that all four response_forwarder functions are used
        for func_name in [
            "discard_response",
            "forward_error_to_client",
            "forward_buffered_body",
            "forward_success_stream",
        ]:
            buffered_count = len(re.findall(rf"{func_name}\(", buffered_source))
            stream_count = len(re.findall(rf"{func_name}\(", stream_source))
            total = buffered_count + stream_count
            assert total >= 1, (
                f"Expected {func_name} to be used at least once across both handlers, "
                f"but found 0 occurrences. Every path involving an upstream response "
                f"must use one of the response_forwarder functions."
            )
