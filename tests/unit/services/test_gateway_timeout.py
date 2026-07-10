"""
Unit tests for timeout handling in _handle_buffered_retryable_request.

Tests cover:
  1. Timeout fires during retry loop → 504 JSONResponse
  2. Timeout does not fire for fast failure
  3. Backoff sleeps are counted within the deadline
  4. Timeout exhaustion response includes structured data
  7. Timeout with open stream → discard_response calls aclose
  8. Timeout after discard is safe no-op
  9. Timeout before proxy_request skips discard
  10. discard_response failure is logged, not raised
  21. Retry failure log includes key and status
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.responses import JSONResponse

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.gateway_service import _handle_buffered_retryable_request
from src.services.gateway.response_forwarder import (
    discard_response as _real_discard_response,
)

# Save a reference to the real asyncio.sleep before any patching.
# When ``asyncio.sleep`` is patched, all modules sharing the same
# ``asyncio`` module reference see the replacement.  This alias
# lets helpers that replace ``asyncio.sleep`` still call the real one.
_real_asyncio_sleep = asyncio.sleep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_for_retry(
    instance_name: str = "deepseek-home",
    debug_mode: str = "disabled",
    retry_enabled: bool = True,
    timeout_total: float = 600.0,
    key_error_attempts: int = 3,
    key_error_backoff_sec: float = 0.1,
    key_error_backoff_factor: float = 1.0,
    server_error_attempts: int = 3,
    server_error_backoff_sec: float = 0.1,
    server_error_backoff_factor: float = 1.0,
) -> MagicMock:
    """Create a mock FastAPI Request with retry policy and timeout config.

    Args:
        instance_name: Provider instance name.
        debug_mode: Effective debug mode for the provider.
        retry_enabled: Whether retry policy is enabled.
        timeout_total: Total timeout in seconds (float, not Mock).
        key_error_attempts: Max key error retry attempts.
        key_error_backoff_sec: Base backoff for key errors.
        key_error_backoff_factor: Backoff multiplier for key errors.
        server_error_attempts: Max server error retry attempts.
        server_error_backoff_sec: Base backoff for server errors.
        server_error_backoff_factor: Backoff multiplier for server errors.

    Returns:
        Mocked FastAPI Request with all needed app.state dependencies.
    """
    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.url.query = ""
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

    # Cache
    mock_cache = MagicMock()
    mock_cache.get_key_from_pool = Mock(return_value=(1, "sk-test-key"))
    mock_cache.remove_key_from_pool = AsyncMock()

    # HTTP client factory
    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(return_value=MagicMock())

    # DB manager
    mock_db_manager = MagicMock()

    # Config accessor + provider config
    mock_accessor = MagicMock()
    mock_provider_config = MagicMock()
    mock_provider_config.gateway_policy = MagicMock()
    mock_provider_config.gateway_policy.retry.enabled = retry_enabled
    mock_provider_config.gateway_policy.debug_mode = debug_mode
    mock_provider_config.timeouts = MagicMock()
    mock_provider_config.timeouts.total = timeout_total

    # Retry policies
    key_error_policy = MagicMock()
    key_error_policy.attempts = key_error_attempts
    key_error_policy.backoff_sec = key_error_backoff_sec
    key_error_policy.backoff_factor = key_error_backoff_factor
    mock_provider_config.gateway_policy.retry.on_key_error = key_error_policy

    server_error_policy = MagicMock()
    server_error_policy.attempts = server_error_attempts
    server_error_policy.backoff_sec = server_error_backoff_sec
    server_error_policy.backoff_factor = server_error_backoff_factor
    mock_provider_config.gateway_policy.retry.on_server_error = server_error_policy

    mock_accessor.get_provider_or_raise = Mock(return_value=mock_provider_config)

    request.app = MagicMock()
    request.app.state.gateway_cache = mock_cache
    request.app.state.http_client_factory = mock_http_factory
    request.app.state.db_manager = mock_db_manager
    request.app.state.accessor = mock_accessor
    request.app.state.debug_mode_map = {instance_name: debug_mode}

    return request


def _make_provider() -> AsyncMock:
    """Create a mock IProvider with parse_request_details returning a valid model."""
    provider = AsyncMock()
    provider.proxy_request = AsyncMock()
    provider.parse_request_details = AsyncMock(
        return_value=MagicMock(model_name="gpt-4")
    )
    return provider


def _make_upstream_response(status_code: int = 200) -> AsyncMock:
    """Create a mock httpx.Response."""
    response = AsyncMock()
    response.status_code = status_code
    response.headers = {}
    response.aread = AsyncMock(return_value=b"{}")
    response.aclose = AsyncMock()
    response.aiter_bytes = MagicMock()
    return response


def _make_fail_result(reason: ErrorReason, status_code: int = 500) -> CheckResult:
    """Create a failing CheckResult with the given reason."""
    return CheckResult.fail(reason, status_code=status_code)


def _make_success_result() -> CheckResult:
    """Create a successful CheckResult."""
    return CheckResult.success(status_code=200)


class _ImmediateTimeout:
    """A context manager that raises TimeoutError immediately on __aenter__.

    Used to simulate a timeout that fires before any proxy_request call,
    bypassing real wall-clock waiting.
    """

    def __init__(self, delay: float) -> None:
        pass

    async def __aenter__(self) -> None:
        raise TimeoutError()

    async def __aexit__(self, *args: object) -> bool:
        return False


# ---------------------------------------------------------------------------
# Scenario #1 — Timeout fires during retry loop
# ---------------------------------------------------------------------------


class TestTimeoutFiresDuringRetryLoop:
    """Tests for timeout firing during the retry loop."""

    @pytest.mark.asyncio
    async def test_timeout_returns_504_when_loop_exceeds_deadline(self):
        """Provider hangs → timeout fires → 504 JSONResponse."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,  # Very short deadline
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)

        # Return a retryable error so the loop continues and hits backoff sleep
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        # Make asyncio.sleep actually sleep long enough for the timeout to fire.
        # 50ms is much longer than the 1ms timeout deadline.
        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

        # Save a reference to the discard_response mock so we can verify
        # the finally block invokes it (Design Decision 4).
        mock_discard = AsyncMock()

        with (
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=mock_discard,
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
                request, provider, "deepseek-home"
            )

        # Verify 504 JSON response
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        # Verify the finally block called discard_response
        mock_discard.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_response_contains_structured_data(self):
        """504 body contains error, attempts, and last_error fields."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

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
                request, provider, "deepseek-home"
            )

        # Parse the JSONResponse body
        body = bytes(result.body)
        assert b'"error"' in body
        assert b'"attempts"' in body
        assert b'"last_error"' in body

        content = json.loads(body)
        assert "error" in content
        assert "attempts" in content
        assert content["attempts"] >= 1
        assert "last_error" in content
        assert content["last_error"] == "network_error"
        assert "Gateway timeout" in content["error"]


# ---------------------------------------------------------------------------
# Scenario #2 — Timeout does not fire for fast failure
# ---------------------------------------------------------------------------


class TestTimeoutDoesNotFireForFastFailure:
    """Tests verifying timeout does not trigger when failures are fast."""

    @pytest.mark.asyncio
    async def test_all_retries_complete_without_timeout(self):
        """Fast NETWORK_ERROR retries complete successfully without timeout."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,  # Large timeout
            server_error_attempts=3,
            server_error_backoff_sec=0.0,  # Instant backoff
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        ok_response = _make_upstream_response(status_code=200)
        ok_result = _make_success_result()

        # 3 failures, then success
        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (fail_response, fail_result, b""),
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock()

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
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        # Should succeed after retries, not timeout
        assert result is mock_streaming_response
        assert provider.proxy_request.call_count == 4

    @pytest.mark.asyncio
    async def test_server_error_retries_then_key_rotation_without_timeout(self):
        """3 server retries exhausted → key rotated → succeeds, no timeout."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,
            server_error_attempts=3,
            server_error_backoff_sec=0.0,
            key_error_attempts=3,
            key_error_backoff_sec=0.0,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        ok_response = _make_upstream_response(status_code=200)
        ok_result = _make_success_result()

        # 3 server errors (exhausts server retries)
        # → key rotation + 1 more attempt succeeds
        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (fail_response, fail_result, b""),
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock()

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
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        # Should succeed after key rotation, no timeout
        assert result is mock_streaming_response
        assert provider.proxy_request.call_count == 4


# ---------------------------------------------------------------------------
# Scenario #3 — Backoff sleeps are counted within the deadline
# ---------------------------------------------------------------------------


class TestBackoffSleepsCountedWithinDeadline:
    """Tests verifying backoff sleeps happen inside the timeout context."""

    @pytest.mark.asyncio
    async def test_sleep_called_inside_timeout_context(self):
        """asyncio.sleep for backoff is called while timeout context is active."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,
            server_error_attempts=3,
            server_error_backoff_sec=0.0,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        # Track whether sleep is called while timeout is active
        timeout_is_active = False
        sleep_called_during_timeout = False

        class _TrackingTimeout:
            """A context manager that tracks when the timeout block is active."""

            def __init__(self, delay: float) -> None:
                self.delay = delay

            async def __aenter__(self) -> "_TrackingTimeout":
                nonlocal timeout_is_active
                timeout_is_active = True
                return self

            async def __aexit__(self, *args: object) -> bool:
                nonlocal timeout_is_active
                timeout_is_active = False
                return False

        async def _tracking_sleep(delay: float) -> None:
            nonlocal sleep_called_during_timeout
            if timeout_is_active:
                sleep_called_during_timeout = True

        with (
            patch("asyncio.timeout", _TrackingTimeout),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _tracking_sleep,
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            # The loop will exhaust server retries (3 attempts), then rotate
            # key and continue. The _tracking_sleep should be called during
            # backoff inside the _TrackingTimeout context.
            await _handle_buffered_retryable_request(request, provider, "deepseek-home")

        assert (
            sleep_called_during_timeout
        ), "Backoff sleep must be called while asyncio.timeout context is active"

    @pytest.mark.asyncio
    async def test_short_timeout_fires_during_backoff_sleep(self):
        """When backoff sleep exceeds deadline, timeout fires during sleep."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_attempts=3,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        async def _long_sleep(_delay: float) -> None:
            # Sleep longer than timeout deadline to ensure timeout fires
            await _real_asyncio_sleep(0.05)

        with (
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _long_sleep,
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        # Timeout should fire during backoff sleep → 504
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        content = json.loads(bytes(result.body))
        assert (
            content["attempts"] >= 1
        ), "Should have completed at least 1 attempt before timeout fired"


# ---------------------------------------------------------------------------
# Scenario #4 — Timeout exhaustion response includes structured data
# ---------------------------------------------------------------------------


class TestTimeoutExhaustionResponse:
    """Tests the structure of the 504 timeout response."""

    @pytest.mark.asyncio
    async def test_response_is_jsonresponse_with_504(self):
        """Timeout returns a JSONResponse with 504 status code."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

        with (
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _long_sleep,
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

    @pytest.mark.asyncio
    async def test_body_contains_error_attempts_last_error(self):
        """504 body has exactly the expected keys: error, attempts, last_error."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

        with (
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _long_sleep,
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        content = json.loads(bytes(result.body))

        assert set(content.keys()) == {
            "error",
            "attempts",
            "last_error",
        }, f"Expected keys: error, attempts, last_error. Got: {set(content.keys())}"
        assert isinstance(content["error"], str)
        assert isinstance(content["attempts"], int)
        assert isinstance(content["last_error"], str)

    @pytest.mark.asyncio
    async def test_error_message_includes_timeout_value(self):
        """The error string mentions the timeout duration in seconds."""
        timeout_s = 30.0
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=timeout_s,
        )
        provider = _make_provider()

        # Use a controlled timeout that raises immediately so we can
        # verify the error message format without waiting real time.
        class _ImmediateTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise TimeoutError()

            async def __aexit__(self, *args: object) -> bool:
                return False

        with (
            patch("asyncio.timeout", _ImmediateTimeout),
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
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        content = json.loads(bytes(result.body))
        assert (
            "30s" in content["error"]
        ), f"Error message should mention the 30s timeout. Got: {content['error']}"

    @pytest.mark.asyncio
    async def test_last_error_is_unknown_when_no_attempts_completed(self):
        """When timeout fires immediately without any attempt, last_error='unknown'."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        # Make asyncio.sleep raise TimeoutError to simulate an immediate timeout
        # that fires before the first proxy_request completes.
        async def _raising_sleep(_delay: float) -> None:
            raise TimeoutError()

        with (
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                _raising_sleep,
            ),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
        ):
            # The timeout fires at the first sleep/await point → no attempt
            # completes. But the timeout wrapping catches it.
            # Actually, without patching asyncio.timeout, this will raise
            # an unhandled TimeoutError, not go through the except clause.
            pass

        # Rewrite: patch asyncio.timeout to raise immediately
        class _ImmediateTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise TimeoutError()

            async def __aexit__(self, *args: object) -> bool:
                return False

        with (
            patch("asyncio.timeout", _ImmediateTimeout),
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
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        content = json.loads(bytes(result.body))
        assert (
            content["attempts"] == 0
        ), "No attempt should have completed when timeout fires immediately"
        assert (
            content["last_error"] == "unknown"
        ), "last_error should be 'unknown' when no attempt completed"


# ---------------------------------------------------------------------------
# Scenario #21 — Retry failure log includes key and status
# ---------------------------------------------------------------------------


class TestRetryFailureLogIncludesKeyAndStatus:
    """Tests that retry failure log messages include key ID and upstream status."""

    @pytest.mark.asyncio
    async def test_log_includes_attempt_key_and_status(self):
        """Log warning on failure includes attempt number, reason, key, status."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,
            server_error_attempts=3,
            server_error_backoff_sec=0.0,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)
        ok_response = _make_upstream_response(status_code=200)
        ok_result = _make_success_result()

        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock()

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
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
            patch("src.services.gateway.gateway_service.logger") as mock_logger,
        ):
            await _handle_buffered_retryable_request(request, provider, "deepseek-home")

        # The warning log should contain the expected format
        warning_calls = list(mock_logger.warning.call_args_list)
        found = False
        for c in warning_calls:
            msg = c[0][0] if c[0] else ""
            if "Attempt 1 failed" in msg and "'deepseek-home'" in msg:
                assert (
                    "[network_error]" in msg
                ), f"Log should contain error reason. Got: {msg}"
                assert "Key: #1" in msg, f"Log should contain key ID. Got: {msg}"
                assert (
                    "Status: 503" in msg
                ), f"Log should contain upstream status. Got: {msg}"
                found = True
                break

        assert found, (
            f"Expected warning log with 'Attempt 1 failed for 'deepseek-home'' "
            f"not found. Warnings: {warning_calls}"
        )

    @pytest.mark.asyncio
    async def test_log_uses_correct_key_id_for_each_attempt(self):
        """Log uses the key ID from the pool, not a hardcoded value."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,
            key_error_attempts=3,
            key_error_backoff_sec=0.0,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=401)
        fail_result = _make_fail_result(ErrorReason.INVALID_KEY, status_code=401)

        # First key is #42, fails with INVALID_KEY → gets blacklisted
        # Second key is #99, also fails → key rotation exhausted
        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (fail_response, fail_result, b""),
        ]

        # Return key #42 first, then key #99
        request.app.state.gateway_cache.get_key_from_pool.side_effect = [
            (42, "sk-key-42"),
            (99, "sk-key-99"),
            None,
        ]

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
                new=AsyncMock(),
            ),
            patch("src.services.gateway.gateway_service.logger") as mock_logger,
        ):
            await _handle_buffered_retryable_request(request, provider, "deepseek-home")

        # Collect all warning messages
        warning_messages = [c[0][0] for c in mock_logger.warning.call_args_list if c[0]]

        # First attempt should mention key #42
        attempt_1_msgs = [m for m in warning_messages if "Attempt 1" in m]
        assert len(attempt_1_msgs) >= 1
        assert (
            "Key: #42" in attempt_1_msgs[0]
        ), f"Attempt 1 should mention key #42. Got: {attempt_1_msgs[0]}"

        # Second attempt should mention key #99
        attempt_2_msgs = [m for m in warning_messages if "Attempt 2" in m]
        assert len(attempt_2_msgs) >= 1
        assert (
            "Key: #99" in attempt_2_msgs[0]
        ), f"Attempt 2 should mention key #99. Got: {attempt_2_msgs[0]}"

    @pytest.mark.asyncio
    async def test_log_reason_matches_error_reason_enum(self):
        """Log reason string matches the ErrorReason enum value."""
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=600.0,
            server_error_attempts=3,
            server_error_backoff_sec=0.0,
        )
        provider = _make_provider()

        # Test with RATE_LIMITED reason
        fail_response = _make_upstream_response(status_code=429)
        fail_result = _make_fail_result(ErrorReason.RATE_LIMITED, status_code=429)
        ok_response = _make_upstream_response(status_code=200)
        ok_result = _make_success_result()

        provider.proxy_request.side_effect = [
            (fail_response, fail_result, b""),
            (ok_response, ok_result, b'{"ok": true}'),
        ]

        mock_streaming_response = MagicMock()

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
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.forward_success_stream",
                new=AsyncMock(return_value=mock_streaming_response),
            ),
            patch("src.services.gateway.gateway_service.logger") as mock_logger,
        ):
            await _handle_buffered_retryable_request(request, provider, "deepseek-home")

        warning_messages = [c[0][0] for c in mock_logger.warning.call_args_list if c[0]]
        attempt_msgs = [m for m in warning_messages if "Attempt 1" in m]
        assert len(attempt_msgs) >= 1
        assert (
            "[rate_limited]" in attempt_msgs[0]
        ), f"Attempt log should contain [rate_limited]. Got: {attempt_msgs[0]}"
        assert (
            "Status: 429" in attempt_msgs[0]
        ), f"Attempt log should contain Status: 429. Got: {attempt_msgs[0]}"


# ---------------------------------------------------------------------------
# Scenario #7-10 — Timeout discard_response behavior (Design Decision 4)
# ---------------------------------------------------------------------------


class TestTimeoutDiscardResponse:
    """Tests for discard_response behavior in the finally block on timeout.

    These tests verify Design Decision 4: the finally block guarantees
    upstream response closure on timeout by calling discard_response,
    regardless of whether the stream is open or already closed.
    """

    @pytest.mark.asyncio
    async def test_timeout_calls_discard_response_with_open_stream(self):
        """Timeout with body_bytes=None (open stream) → discard_response calls aclose.

        When proxy_request returns body_bytes=None, the stream is still open.
        The finally block calls discard_response(upstream_response, None),
        which invokes upstream_response.aclose().
        """
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)

        # body_bytes=None means the stream is still open
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            None,
        )

        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

        # Use side_effect to delegate to the real discard_response so that
        # aclose() is actually invoked, while the mock tracks calls.
        mock_discard = AsyncMock(side_effect=_real_discard_response)

        with (
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=mock_discard,
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
                request, provider, "deepseek-home"
            )

        # Assert 504 JSONResponse returned
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        # Assert discard_response was called (in both retry loop and finally)
        mock_discard.assert_called()

        # Assert the finally block call used the upstream response and
        # body_bytes=None (the last call is from the finally block)
        mock_discard.assert_called_with(fail_response, None)

        # Assert aclose() was invoked (since body_bytes=None means open stream)
        fail_response.aclose.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_after_discard_is_safe_noop(self):
        """Timeout with body_bytes=b"" (already read) → discard_response is a no-op.

        When proxy_request returns body_bytes=b"", the body was already read
        and the connection is closed. discard_response with body_bytes=b"" is
        a safe no-op — it does NOT call aclose().
        """
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)

        # body_bytes=b"" means the body was already read (stream closed)
        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        async def _long_sleep(_delay: float) -> None:
            await _real_asyncio_sleep(0.05)

        # Use side_effect to delegate to the real discard_response so that
        # we can verify aclose() is NOT called when body_bytes is not None.
        mock_discard = AsyncMock(side_effect=_real_discard_response)

        with (
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=mock_discard,
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
                request, provider, "deepseek-home"
            )

        # Assert 504 JSONResponse returned
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        # Assert discard_response was called (in finally block)
        mock_discard.assert_called()

        # Assert aclose() was NOT called (since body_bytes is not None → no-op)
        fail_response.aclose.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_before_proxy_request_skips_discard(self):
        """Timeout before any proxy_request → discard_response not called.

        When the timeout fires immediately (before any proxy_request call),
        upstream_response is still None. The finally block checks
        `if upstream_response is not None` and skips discard_response.
        """
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
        )
        provider = _make_provider()

        mock_discard = AsyncMock()

        with (
            patch("asyncio.timeout", _ImmediateTimeout),
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=mock_discard,
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        # Assert 504 JSONResponse returned
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        # Assert discard_response was NOT called (upstream_response is None)
        mock_discard.assert_not_called()

        # Assert attempts=0 and last_error="unknown"
        content = json.loads(bytes(result.body))
        assert content["attempts"] == 0
        assert content["last_error"] == "unknown"

    @pytest.mark.asyncio
    async def test_discard_response_failure_logged_not_raised(self):
        """discard_response raising in finally → logged, not raised, 504 returned.

        When the timeout fires DURING discard_response in the retry loop,
        _response_handled stays False (the assignment after discard_response
        is never reached). The finally block then calls discard_response
        again, which raises RuntimeError. The exception is caught by the
        inner try/except, logger.error is called with exc_info=True, and
        the original 504 JSONResponse from the except TimeoutError block
        is still returned.
        """
        request = _make_request_for_retry(
            instance_name="deepseek-home",
            timeout_total=0.001,
            server_error_backoff_sec=0.01,
        )
        provider = _make_provider()

        fail_response = _make_upstream_response(status_code=503)
        fail_result = _make_fail_result(ErrorReason.NETWORK_ERROR, status_code=503)

        provider.proxy_request.return_value = (
            fail_response,
            fail_result,
            b"",
        )

        # discard_response is called twice:
        # 1st call (in retry loop) → hangs so the 0.001s timeout fires
        #   DURING it, leaving _response_handled = False.
        # 2nd call (in finally block) → raises RuntimeError.
        discard_call_count = 0

        async def _mock_discard(resp: object, body: object) -> None:
            nonlocal discard_call_count
            discard_call_count += 1
            if discard_call_count == 1:
                # Hang so timeout fires during discard_response in the loop.
                await _real_asyncio_sleep(0.05)
            else:
                raise RuntimeError("discard failed")

        with (
            patch(
                "src.services.gateway.gateway_service.discard_response",
                new=_mock_discard,
            ),
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ),
            patch("src.services.gateway.gateway_service.logger") as mock_logger,
        ):
            result = await _handle_buffered_retryable_request(
                request, provider, "deepseek-home"
            )

        # Assert 504 JSONResponse was still returned (not masked by RuntimeError)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 504

        # Assert discard_response was called exactly twice:
        # 1st in the retry loop (hung → timeout), 2nd in finally (raised).
        assert discard_call_count == 2

        # Assert logger.error was called with exc_info=True (from the finally
        # block's inner except clause)
        error_calls = mock_logger.error.call_args_list
        assert any(call.kwargs.get("exc_info") is True for call in error_calls), (
            "logger.error should have been called with exc_info=True when "
            "discard_response raised in the finally block. "
            f"Error calls: {error_calls}"
        )
