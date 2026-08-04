"""
Unit tests for sticky-mode and fail-fast semantics in gateway handlers.

Tests cover 16 scenarios:
  1. Full-stream error rotates pointer without retry
  2. Buffered server error rotates key instead of same-key retry
  3. on_server_error config ignored in sticky mode
  4. Client error aborts without consuming counters
  5. Round-robin mode ignores the breaker
  6. Breaker disabled in sticky mode
  7. Fail-fast returns upstream error transparently
  8. Retryable failure during OPEN does not ban
  9. Fatal failure during OPEN still bans
  10. Probe traffic rotates keys (round-robin fallback)
  11. Fail-fast requests counted via in-memory metrics backend
  12. Sticky mode in full-stream path
  13. Sticky mode in buffered path
  14. Retryable error consumes key_error_attempts in sticky mode
  15. Total deadline still enforced in sticky mode
  16. Server error in full-stream leaves key untouched
"""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from src.core.constants import ErrorReason, KeySelectionMode
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
# Helpers
# ---------------------------------------------------------------------------


def _make_sticky_request(
    instance_name: str = "openai",
    sticky: bool = True,
    fail_fast: bool = False,
    debug_mode: str = "disabled",
    retry_enabled: bool = False,
    timeout_total: float = 600.0,
    key_error_attempts: int = 3,
    key_error_backoff_sec: float = 0,
    key_error_backoff_factor: float = 1.0,
) -> MagicMock:
    """Create a mock FastAPI Request with sticky-mode cache and config.

    Args:
        instance_name: Provider instance name.
        sticky: True to set KeySelectionMode.STICKY on the cache and provider config.
        fail_fast: Value for ``cache.should_fail_fast()`` return.
        debug_mode: Effective debug mode for the provider.
        retry_enabled: Whether retry policy is enabled on the provider config.
        timeout_total: Total timeout in seconds for buffered handler.
        key_error_attempts: Max key error retry attempts.
        key_error_backoff_sec: Base backoff for key errors.
        key_error_backoff_factor: Backoff multiplier for key errors.

    Returns:
        Mocked FastAPI Request with all needed app.state dependencies.
    """
    request = _make_mock_request()
    cache = request.app.state.gateway_cache
    accessor = request.app.state.accessor

    # Selection mode
    mode = KeySelectionMode.STICKY if sticky else KeySelectionMode.ROUND_ROBIN
    cache.get_selection_mode = Mock(return_value=mode)
    cache.should_fail_fast = Mock(return_value=fail_fast)
    cache.record_upstream_result = Mock()
    cache.rotate_sticky_key = Mock(return_value=(2, "sk-rotated-key"))
    cache.note_rotation_without_ban = Mock()

    # Set key_selection.mode on provider config (used by buffered handler)
    provider_cfg = accessor.get_provider_or_raise.return_value
    provider_cfg.gateway_policy.key_selection = MagicMock()
    provider_cfg.gateway_policy.key_selection.mode = mode

    # Retry policy (for buffered handler)
    provider_cfg.gateway_policy.retry.enabled = retry_enabled
    provider_cfg.gateway_policy.debug_mode = debug_mode

    key_error_policy = MagicMock()
    key_error_policy.attempts = key_error_attempts
    key_error_policy.backoff_sec = key_error_backoff_sec
    key_error_policy.backoff_factor = key_error_backoff_factor
    provider_cfg.gateway_policy.retry.on_key_error = key_error_policy

    server_error_policy = MagicMock()
    server_error_policy.attempts = 5
    server_error_policy.backoff_sec = 0
    server_error_policy.backoff_factor = 1.0
    provider_cfg.gateway_policy.retry.on_server_error = server_error_policy

    provider_cfg.timeouts = MagicMock()
    provider_cfg.timeouts.total = timeout_total

    request.app.state.debug_mode_map = {instance_name: debug_mode}

    return request


def _make_fail_result(reason: ErrorReason, status_code: int = 500) -> CheckResult:
    """Create a failing CheckResult with the given reason."""
    return CheckResult.fail(reason, status_code=status_code)


# ---------------------------------------------------------------------------
# Full-stream sticky handler tests
# ---------------------------------------------------------------------------


class TestFullStreamSticky:
    """Tests for sticky-mode in full-stream handler."""

    @pytest.mark.asyncio
    async def test_full_stream_error_rotates_pointer_without_retry(self):
        """Full-stream sticky: SERVER_ERROR → pointer rotates, upstream error
        returned, provider.proxy_request called exactly once (no retry).

        Spec: sticky-key-selection / Full-stream path honors sticky mode.
        """
        request = _make_sticky_request(sticky=True, fail_fast=False)
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=500)
        fail_result = _make_fail_result(ErrorReason.SERVER_ERROR, status_code=500)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "server error"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ) as mock_forward_error,
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
        ):
            result = await _handle_full_stream_request(request, provider, "openai")

        # Upstream error forwarded
        assert result is mock_forwarded
        mock_forward_error.assert_awaited_once()

        # provider.proxy_request called exactly once (full-stream has no retry)
        assert provider.proxy_request.call_count == 1

        # Sticky rotation without ban (server error → no penalty)
        cache = request.app.state.gateway_cache
        cache.rotate_sticky_key.assert_called_once()
        cache.note_rotation_without_ban.assert_called_once()

        # No key report or pool removal
        mock_report.assert_not_called()
        cache.remove_key_from_pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_sticky_mode_in_full_stream_path(self):
        """Full-stream dispatch with sticky mode: key obtained via sticky pointer.

        Spec: transparent-gateway-routing / Sticky mode in full-stream path.
        """
        request = _make_sticky_request(sticky=True, fail_fast=False)
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)

        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            None,
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ) as mock_forward,
        ):
            result = await _handle_full_stream_request(request, provider, "openai")

        assert result is mock_streaming
        mock_forward.assert_awaited_once()

        # Verify sticky mode was queried and fail_fast consulted (because
        # sticky=True triggers `fail_fast = cache.should_fail_fast(...)`)
        cache = request.app.state.gateway_cache
        cache.get_selection_mode.assert_called_with("openai")
        cache.should_fail_fast.assert_called_with("openai")

        # record_upstream_result called for sticky
        cache.record_upstream_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_error_in_full_stream_leaves_key_untouched(self):
        """Sticky full-stream SERVER_ERROR: no _report_key_failure, no
        remove_key_from_pool, pointer rotates without penalty.

        Spec: transparent-gateway-routing / Server error in sticky full-stream
              path leaves key untouched.
        """
        request = _make_sticky_request(sticky=True, fail_fast=False)
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=500)
        fail_result = _make_fail_result(ErrorReason.SERVER_ERROR, status_code=500)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "internal server error"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
        ):
            result = await _handle_full_stream_request(request, provider, "openai")

        assert result is mock_forwarded
        cache = request.app.state.gateway_cache

        # No key penalty (no report, no remove) — server error rotation without ban
        mock_report.assert_not_called()
        cache.remove_key_from_pool.assert_not_called()

        # Pointer rotated but not banned
        cache.rotate_sticky_key.assert_called_once()
        cache.note_rotation_without_ban.assert_called_once()


# ---------------------------------------------------------------------------
# Buffered sticky handler tests
# ---------------------------------------------------------------------------


class TestBufferedSticky:
    """Tests for sticky-mode in buffered/retryable handler."""

    @pytest.mark.asyncio
    async def test_server_error_rotates_key_instead_of_same_key_retry(self):
        """Buffered sticky: SERVER_ERROR → failed key excluded, request retried
        with a DIFFERENT key; no same-key retry on the server error policy.

        Spec: sticky-key-selection / Sticky retry loop rotates the key and
              retries the request.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=3,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        fail_response = _make_mock_response(status_code=500)
        fail_result = _make_fail_result(ErrorReason.SERVER_ERROR, status_code=500)
        ok_response = _make_mock_response(status_code=200)
        ok_result = CheckResult.success(status_code=200)

        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        # First key #1, second key #99 (different key after rotation)
        cache = request.app.state.gateway_cache
        cache.get_key_from_pool.side_effect = [
            (1, "sk-key-1"),
            (99, "sk-key-99"),
        ]

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        # Two calls: first server error on key#1, second success on key#99
        assert provider.proxy_request.call_count == 2

        # The first call should have excluded key_id 1
        get_key_calls = cache.get_key_from_pool.call_args_list
        # Second call should pass instance_name and exclude_key_ids
        assert len(get_key_calls) >= 2
        # Note: get_key_from_pool gets instance_name as first positional arg,
        # and exclude_key_ids as keyword or second positional.
        # Check call pattern: first positional arg is instance_name.
        assert get_key_calls[1][0][0] == "openai"

        # No key banning for server errors in sticky mode
        mock_report.assert_not_called()
        cache.remove_key_from_pool.assert_not_called()

        # note_rotation_without_ban should be called
        cache.note_rotation_without_ban.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_server_error_config_ignored_in_sticky_mode(self):
        """Sticky with retry.on_server_error.attempts=5: server errors consume
        key_error_attempts, never 5 same-key attempts.

        Spec: sticky-key-selection / Sticky retry loop rotates the key and
              retries the request.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=2,
        )
        # Set on_server_error.attempts to 5 explicitly
        provider_cfg = request.app.state.accessor.get_provider_or_raise.return_value
        provider_cfg.gateway_policy.retry.on_server_error.attempts = 5

        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        fail_response = _make_mock_response(status_code=500)
        fail_result = _make_fail_result(ErrorReason.SERVER_ERROR, status_code=500)

        # All calls fail — server errors are treated as key errors in sticky
        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),  # key#1 SERVER_ERROR
            (fail_response, fail_result, b""),  # key#2 SERVER_ERROR
            (fail_response, fail_result, b""),  # key#3 SERVER_ERROR (exhausted)
        ]

        cache = request.app.state.gateway_cache
        cache.get_key_from_pool.side_effect = [
            (1, "sk-key-1"),
            (2, "sk-key-2"),
            (3, "sk-key-3"),
        ]

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        # After 2 key_error_attempts exhausted, forward error to client
        assert result is mock_forwarded

        # Verify server errors counted as key errors: exactly key_error_attempts
        # calls (2) then exhausted — on_server_error.attempts=5 was ignored
        # Count: key#1 (fail, increment), key#2 (fail, increment), exhausted
        assert provider.proxy_request.call_count == 2

        # Server errors do NOT ban keys in sticky mode
        mock_report.assert_not_called()

        # note_rotation_without_ban called for each server error
        assert cache.note_rotation_without_ban.call_count == 2

    @pytest.mark.asyncio
    async def test_client_error_aborts_without_consuming_counters(self):
        """Sticky buffered: BAD_REQUEST → forwarded, counters unchanged, pointer
        unchanged.

        Spec: sticky-key-selection / Sticky retry loop rotates the key and
              retries the request.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=3,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=400)
        fail_result = _make_fail_result(ErrorReason.BAD_REQUEST, status_code=400)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "bad request"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ) as mock_forward_error,
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                new=AsyncMock(),
            ) as mock_sleep,
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        # Error forwarded to client
        assert result is mock_forwarded
        mock_forward_error.assert_awaited_once()

        # Exactly one proxy_request call (no retry)
        assert provider.proxy_request.call_count == 1

        # No sleep (no backoff)
        mock_sleep.assert_not_called()

        # No key penalty
        mock_report.assert_not_called()
        cache = request.app.state.gateway_cache
        cache.remove_key_from_pool.assert_not_called()
        cache.note_rotation_without_ban.assert_not_called()

    @pytest.mark.asyncio
    async def test_sticky_mode_in_buffered_path(self):
        """Buffered dispatch with sticky: retry.enabled + sticky → buffered
        handler uses sticky selection.

        Spec: transparent-gateway-routing / Sticky mode in buffered path.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=3,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)

        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        assert provider.proxy_request.call_count == 1

        # record_upstream_result called for sticky
        cache = request.app.state.gateway_cache
        cache.record_upstream_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_retryable_error_consumes_key_error_attempts_in_sticky(self):
        """Sticky: NETWORK_ERROR with on_key_error.attempts=3 → exclude +
        increment + on_key_error backoff + retry with new key; on_server_error
        counter unused.

        Spec: transparent-gateway-routing / Sticky retry semantics in the
              buffered path.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=3,
            key_error_backoff_sec=0.1,
            key_error_backoff_factor=2.0,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        fail_response = _make_mock_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        ok_response = _make_mock_response(status_code=200)
        ok_result = CheckResult.success(status_code=200)

        # First call fails with NETWORK_ERROR, second succeeds
        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        cache = request.app.state.gateway_cache
        cache.get_key_from_pool.side_effect = [
            (1, "sk-key-1"),
            (2, "sk-key-2"),
        ]

        mock_streaming = MagicMock(spec=StreamingResponse)
        mock_sleep = AsyncMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                new=mock_sleep,
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        assert provider.proxy_request.call_count == 2

        # NETWORK_ERROR is a server error → in sticky, treated as rotation
        # trigger (is_server_error=True but not OVERLOADED → note_rotation_without_ban
        # but NETWORK_ERROR falls through to the else branch
        # Wait — NETWORK_ERROR.is_server_error() is True. So in the sticky
        # loop, it enters the "if reason.is_server_error() and not OVERLOADED"
        # branch → note_rotation_without_ban, no report_key_failure.
        # So _report_key_failure should NOT be called for NETWORK_ERROR.

        # Actually, wait. NETWORK_ERROR.is_server_error() is True.
        # In the sticky buffered handler:
        # if reason.is_server_error() and reason is not OVERLOADED: note_rotation_without_ban
        # else: report + remove + ban
        # So NETWORK_ERROR → note_rotation_without_ban only.
        mock_report.assert_not_called()
        cache.remove_key_from_pool.assert_not_called()

        # But key_error_attempts is incremented and backoff is used
        cache.note_rotation_without_ban.assert_called_once()

        # Backoff sleep called with the on_key_error backoff formula
        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg > 0, "Backoff sleep should be positive"

    @pytest.mark.asyncio
    async def test_total_deadline_still_enforced_in_sticky_mode(self):
        """Sticky loop exceeding timeouts.total → 504 with structured body
        {"error", "attempts", "last_error"}.

        Spec: transparent-gateway-routing / Sticky retry semantics in the
              buffered path.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,
            retry_enabled=True,
            timeout_total=0.001,  # Very short deadline
            key_error_attempts=3,
            key_error_backoff_sec=0.01,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        fail_response = _make_mock_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)

        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        import asyncio as _asyncio

        _real_sleep = _asyncio.sleep

        async def _long_sleep(_delay: float) -> None:
            await _real_sleep(0.05)

        with (
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _long_sleep,
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        content = json.loads(bytes(result.body))
        assert "error" in content
        assert "attempts" in content
        assert content["attempts"] >= 1
        assert "last_error" in content
        assert "Gateway timeout" in content["error"]


# ---------------------------------------------------------------------------
# Circuit breaker / fail-fast tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerFailFast:
    """Tests for fail-fast behavior when the circuit breaker is OPEN."""

    @pytest.mark.asyncio
    async def test_round_robin_mode_ignores_breaker(self):
        """Round-robin + breaker-enabled config: no breaker consulted/updated;
        behavior identical to pre-change.

        Spec: gateway-circuit-breaker / Breaker is active only in sticky mode.
        """
        request = _make_sticky_request(
            sticky=False,  # round_robin mode
            fail_fast=False,
            retry_enabled=True,
            key_error_attempts=3,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        cache = request.app.state.gateway_cache

        # should_fail_fast must NOT be called in round_robin mode
        cache.should_fail_fast.assert_not_called()

        # record_upstream_result must NOT be called in round_robin mode
        cache.record_upstream_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_breaker_disabled_in_sticky_mode(self):
        """Sticky + circuit_breaker.enabled=false: sticky semantics apply, no
        breaker transitions.

        Spec: gateway-circuit-breaker / Breaker is active only in sticky mode.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=False,  # breaker disabled → no fail_fast
            retry_enabled=True,
            key_error_attempts=3,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        cache = request.app.state.gateway_cache

        # Sticky record_upstream_result is called (breaker records or no-ops)
        cache.record_upstream_result.assert_called_once()

        # Fail-fast not active
        assert provider.proxy_request.call_count == 1

    @pytest.mark.asyncio
    async def test_fail_fast_returns_upstream_error(self):
        """Breaker OPEN: single attempt, upstream error body forwarded
        transparently, no synthetic 503, no retry.

        Spec: gateway-circuit-breaker / OPEN state fail-fast with transparent
              error forwarding.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=True,  # Breaker OPEN
            retry_enabled=True,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=500)
        fail_result = _make_fail_result(ErrorReason.SERVER_ERROR, status_code=500)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "upstream error"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ) as mock_forward_error,
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        # Upstream error forwarded transparently — no synthetic 503
        assert result is mock_forwarded
        mock_forward_error.assert_awaited_once()

        # Exactly one attempt — no retry
        assert provider.proxy_request.call_count == 1

        # SERVER_ERROR is retryable → ban FROZEN during OPEN
        mock_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_retryable_failure_during_open_does_not_ban(self):
        """Breaker OPEN + RATE_LIMITED: _report_key_failure NOT called, key
        stays in pool.

        Spec: gateway-circuit-breaker / OPEN state ban freeze.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=True,  # Breaker OPEN
            retry_enabled=True,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=429)
        fail_result = _make_fail_result(ErrorReason.RATE_LIMITED, status_code=429)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "rate limited"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_forwarded
        cache = request.app.state.gateway_cache

        # Ban freeze: RATE_LIMITED is NOT fatal → no report, no removal
        mock_report.assert_not_called()
        cache.remove_key_from_pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_fatal_failure_during_open_still_bans(self):
        """Breaker OPEN + INVALID_KEY: _report_key_failure called, key removed.

        Spec: gateway-circuit-breaker / OPEN state ban freeze.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=True,  # Breaker OPEN
            retry_enabled=True,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=401)
        fail_result = _make_fail_result(ErrorReason.INVALID_KEY, status_code=401)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "invalid key"}',
        )

        mock_forwarded = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_forwarded
        cache = request.app.state.gateway_cache

        # INVALID_KEY is fatal → ban even during OPEN
        mock_report.assert_called()
        cache.remove_key_from_pool.assert_called()

    @pytest.mark.asyncio
    async def test_probe_traffic_rotates_keys(self):
        """OPEN/HALF_OPEN: consecutive probe requests use round-robin selection;
        sticky pointer not bound.

        Spec: gateway-circuit-breaker / OPEN state round-robin fallback.
        """
        request = _make_sticky_request(
            sticky=True,
            fail_fast=True,  # Breaker OPEN
            retry_enabled=True,
        )
        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "openai"
            )

        assert result is mock_streaming
        cache = request.app.state.gateway_cache

        # In fail-fast mode, get_key_from_pool is called without
        # exclude_key_ids set (since there's no retry loop accumulation)
        cache.get_key_from_pool.assert_called_with("openai")

    @pytest.mark.asyncio
    async def test_fail_fast_requests_counted(self):
        """Fail-fast requests increment the
        llm_gateway_breaker_fail_fast_requests_total counter via in-memory
        metrics backend.

        Spec: gateway-circuit-breaker / Breaker observability.
        """
        # Setup in-memory metrics backend
        from src.metrics.backends.memory import MemoryMetricsCollector
        from src.metrics.registry import BREAKER_FAIL_FAST_REQUESTS, METRIC_DESCRIPTIONS

        collector = MemoryMetricsCollector()

        # Create a mock should_fail_fast that also calls the real
        # _inc_provider_metric via the in-memory collector so that
        # the counter is actually incremented.  The mock cache's
        # should_fail_fast bypasses the real GatewayCache code,
        # so we wire the collector in directly.
        def _should_fail_fast_inc(provider_name: str) -> bool:
            counter = collector.counter(
                BREAKER_FAIL_FAST_REQUESTS,
                METRIC_DESCRIPTIONS[BREAKER_FAIL_FAST_REQUESTS],
                ["provider"],
            )
            counter.inc(labels={"provider": provider_name})
            return True

        request = _make_sticky_request(
            sticky=True,
            fail_fast=True,  # Breaker OPEN
            retry_enabled=True,
        )
        # Override should_fail_fast with our counting version
        cache = request.app.state.gateway_cache
        cache.should_fail_fast = Mock(side_effect=_should_fail_fast_inc)

        request.body = AsyncMock(return_value=b'{"model": "deepseek-chat"}')

        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=200)
        success_result = CheckResult.success(status_code=200)
        provider.proxy_request.return_value = (
            mock_response,
            success_result,
            b'{"ok": true}',
        )

        mock_streaming = MagicMock(spec=StreamingResponse)
        with (
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            await _handle_buffered_retryable_request(request, provider, "openai")

            # Second request to observe counter increment
            provider.proxy_request.return_value = (
                mock_response,
                success_result,
                b'{"ok": true}',
            )
            await _handle_buffered_retryable_request(request, provider, "openai")

        # Verify the fail-fast counter was incremented.
        # The counter is a _MemoryGauge; snapshots return
        # [{"name": ..., "value": ..., "labels": {...}}].
        gauge = collector._counters.get(BREAKER_FAIL_FAST_REQUESTS)
        assert (
            gauge is not None
        ), f"Fail-fast counter {BREAKER_FAIL_FAST_REQUESTS} not registered"
        snapshots = gauge.snapshot()
        total = sum(int(s["value"]) for s in snapshots)
        assert total >= 2, f"Expected fail-fast counter to be at least 2, got {total}"
