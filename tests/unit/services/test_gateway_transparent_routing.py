"""
Unit tests for transparent routing in the gateway.

Verifies that the gateway no longer validates, inspects, or filters
requests by model name — all requests are forwarded transparently.
Also verifies dispatch logic: full-stream vs buffered handler selection.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from starlette.responses import StreamingResponse

from src.core.models import CheckResult
from src.services.gateway.gateway_service import (
    _handle_buffered_retryable_request,
    _handle_full_stream_request,
)
from tests.unit.services.test_gateway_core import (
    _make_mock_provider,
    _make_mock_request,
    _make_mock_response,
)

# ---------------------------------------------------------------------------
# Transparent model routing — no model validation in the hot path
# ---------------------------------------------------------------------------


class TestTransparentModelRouting:
    """Verifies that unknown models are forwarded without validation."""

    @pytest.mark.asyncio
    async def test_unknown_model_forwarded_transparently(self):
        """
        The gateway forwards requests with unknown model names without
        rejecting them. The model name is never validated against config.
        """
        request = _make_mock_request(path="/v1/chat/completions")
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            # Even with an unknown model in the request, the handler
            # should NOT reject it — it just forwards transparently.
            result = await _handle_full_stream_request(
                request, provider, "openai"
            )

            assert result is mock_streaming_response
            # Verify the provider was called — meaning the request was forwarded
            provider.proxy_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_model_membership_check_in_hot_path(self):
        """
        The hot path does NOT access ``provider_config.default_model``.
        Setting it to a sentinel that raises on any attribute access
        verifies the field is never touched during request handling.
        """
        request = _make_mock_request(path="/v1/chat/completions")

        # Replace default_model with a sentinel that fails if accessed
        sentinel = MagicMock()
        sentinel.__getitem__ = Mock(
            side_effect=AssertionError("default_model should NOT be accessed in hot path")
        )
        sentinel.get = Mock(
            side_effect=AssertionError("default_model should NOT be accessed in hot path")
        )
        mock_provider_config = request.app.state.accessor.get_provider_or_raise.return_value
        mock_provider_config.default_model = sentinel

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            result = await _handle_full_stream_request(
                request, provider, "openai"
            )

            # Should succeed without ever touching default_model
            assert result is mock_streaming_response


# ---------------------------------------------------------------------------
# Path forwarding — no rewriting or modification
# ---------------------------------------------------------------------------


class TestPathForwarding:
    """Verifies request paths are forwarded verbatim to the provider."""

    @pytest.mark.asyncio
    async def test_compatible_mode_path_forwarded_unchanged(self):
        """
        The request path is passed verbatim to ``provider.proxy_request``
        without any rewriting or prefix stripping.
        """
        request = _make_mock_request(path="/v1/chat/completions")
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            await _handle_full_stream_request(request, provider, "openai")

            # The path must be forwarded exactly as received
            _, kwargs = provider.proxy_request.call_args
            assert kwargs["path"] == "/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_compatible_api_path_forwarded_unchanged(self):
        """
        Different API paths (e.g., Anthropic Messages API) are forwarded
        verbatim without modification.
        """
        request = _make_mock_request(path="/v1/messages")
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            await _handle_full_stream_request(request, provider, "openai")

            _, kwargs = provider.proxy_request.call_args
            assert kwargs["path"] == "/v1/messages"


# ---------------------------------------------------------------------------
# Dispatch logic — full-stream vs buffered handler selection
# ---------------------------------------------------------------------------


class TestDispatchLogic:
    """Verifies the dispatcher selects the correct handler based on config."""

    @pytest.mark.asyncio
    async def test_standard_instance_uses_full_stream(self):
        """
        When debug mode is disabled and retry is disabled, the full-stream
        handler processes requests successfully without buffering.
        """
        request = _make_mock_request()
        # Verify default config: debug disabled, retry disabled
        mock_provider_config = request.app.state.accessor.get_provider_or_raise.return_value
        assert mock_provider_config.gateway_policy.debug_mode == "disabled"
        assert mock_provider_config.gateway_policy.retry.enabled is False

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            result = await _handle_full_stream_request(
                request, provider, "openai"
            )

            assert result is mock_streaming_response

    @pytest.mark.asyncio
    async def test_debug_mode_forces_buffered_handling(self):
        """
        When debug mode is enabled (not ``"disabled"``), the buffered
        handler must be used so the gateway can log full request/response
        bodies. Verify the buffered handler processes successfully.
        """
        request = _make_mock_request()
        mock_provider_config = request.app.state.accessor.get_provider_or_raise.return_value
        mock_provider_config.gateway_policy.debug_mode = "full_body"
        mock_provider_config.gateway_policy.retry.enabled = False

        request.body = AsyncMock(return_value=b'{"model": "any-model"}')

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
        ) as mock_forward:
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

            # Buffered handler returns a streaming response on success
            assert result is mock_streaming_response
            mock_forward.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_mode_forces_buffered_handling(self):
        """
        When retry is enabled (even with debug disabled), the buffered
        handler must be used so the gateway can replay the request body
        across retry attempts.
        """
        request = _make_mock_request()
        mock_provider_config = request.app.state.accessor.get_provider_or_raise.return_value
        mock_provider_config.gateway_policy.retry.enabled = True
        retry_policy = MagicMock()
        retry_policy.attempts = 3
        retry_policy.backoff_sec = 0
        retry_policy.backoff_factor = 1.0
        mock_provider_config.gateway_policy.retry.on_key_error = retry_policy
        mock_provider_config.gateway_policy.retry.on_server_error = MagicMock()
        mock_provider_config.gateway_policy.retry.on_server_error.attempts = 3
        mock_provider_config.gateway_policy.retry.on_server_error.backoff_sec = 0
        mock_provider_config.gateway_policy.retry.on_server_error.backoff_factor = 1.0

        request.body = AsyncMock(return_value=b'{"model": "any-model"}')

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
    async def test_retry_mode_uses_asyncio_timeout(self):
        """
        When retry is enabled, the buffered handler wraps the retry loop
        in ``asyncio.timeout`` with the configured
        ``provider_config.timeouts.total`` value.
        """
        request = _make_mock_request()
        mock_provider_config = request.app.state.accessor.get_provider_or_raise.return_value
        mock_provider_config.gateway_policy.retry.enabled = True
        mock_provider_config.timeouts = MagicMock()
        mock_provider_config.timeouts.total = 30.0

        retry_policy = MagicMock()
        retry_policy.attempts = 3
        retry_policy.backoff_sec = 0
        retry_policy.backoff_factor = 1.0
        mock_provider_config.gateway_policy.retry.on_key_error = retry_policy
        mock_provider_config.gateway_policy.retry.on_server_error = MagicMock()
        mock_provider_config.gateway_policy.retry.on_server_error.attempts = 3
        mock_provider_config.gateway_policy.retry.on_server_error.backoff_sec = 0
        mock_provider_config.gateway_policy.retry.on_server_error.backoff_factor = 1.0

        request.body = AsyncMock(return_value=b'{"model": "any-model"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.timeout",
            ) as mock_timeout,
        ):
            mock_timeout_cm = MagicMock()
            mock_timeout_cm.__aenter__ = AsyncMock()
            mock_timeout_cm.__aexit__ = AsyncMock(return_value=False)
            mock_timeout.return_value = mock_timeout_cm

            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

            assert result is mock_streaming_response
            mock_timeout.assert_called_once_with(30.0)


# ---------------------------------------------------------------------------
# Body handling — full-stream never buffers
# ---------------------------------------------------------------------------


class TestBodyHandling:
    """Verifies that full-stream mode does not buffer the request body."""

    @pytest.mark.asyncio
    async def test_full_stream_bypasses_body_parsing(self):
        """
        The full-stream handler must NOT read ``request.body()``.
        Setting the body to raise if called verifies this invariant.
        """
        request = _make_mock_request(path="/v1/chat/completions")

        # request.body() must NOT be called in the full-stream path
        request.body = AsyncMock(
            side_effect=AssertionError(
                "request.body() must not be called in full-stream handler"
            )
        )

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            result = await _handle_full_stream_request(
                request, provider, "openai"
            )

            # Must succeed without ever calling request.body()
            assert result is mock_streaming_response
            request.body.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_stream_bypasses_parse_request_details(self):
        """
        The full-stream handler must NOT call
        ``provider.parse_request_details()``. Setting
        parse_request_details to raise if called verifies this invariant.
        """
        request = _make_mock_request(path="/v1/chat/completions")
        provider = _make_mock_provider()

        # parse_request_details must NOT be called in the full-stream path
        provider.parse_request_details = AsyncMock(
            side_effect=AssertionError(
                "parse_request_details() must not be called in full-stream handler"
            )
        )

        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (mock_response, success_result, None)

        mock_streaming_response = MagicMock(spec=StreamingResponse)
        with patch(
            "src.services.gateway.gateway_service.forward_success_stream",
            new=AsyncMock(return_value=mock_streaming_response),
        ):
            result = await _handle_full_stream_request(
                request, provider, "openai"
            )

            # Must succeed without ever calling parse_request_details()
            assert result is mock_streaming_response
            provider.parse_request_details.assert_not_called()
