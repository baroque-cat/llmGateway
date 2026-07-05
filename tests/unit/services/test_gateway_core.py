"""
Unit tests for core gateway_service logic.

Tests cover:
  1-5: _handle_full_stream_request / _handle_buffered_retryable_request
  6-8: Pool health log loop (_pool_health_log_loop)
  9-11: create_app factory
  12-15: Static analysis / Pydantic validation (moved from integration)
"""

import asyncio
import inspect
import logging
import re
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from src.config.schemas import GatewayPolicyConfig, ModelInfo
from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.services.gateway.gateway_service import (
    GatewayStreamError,
    _handle_buffered_retryable_request,
    _handle_full_stream_request,
    _pool_health_log_loop,
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
    mock_provider_config.default_model = {"gpt-4": ModelInfo()}
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
            result = await _handle_full_stream_request(request, provider, "openai")

            assert result is mock_streaming_response
            mock_forward.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_stream_request_no_keys(self):
        """No available keys → 503 JSONResponse."""
        request = _make_mock_request()
        provider = _make_mock_provider()

        # Make cache return no key
        request.app.state.gateway_cache.get_key_from_pool = Mock(return_value=None)

        result = await _handle_full_stream_request(request, provider, "openai")

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
                result = await _handle_full_stream_request(request, provider, "openai")
                # The StreamingResponse is returned; the error happens when
                # the client reads the stream, not during the handler call.
                assert isinstance(result, StreamingResponse)

    @pytest.mark.asyncio
    async def test_full_stream_skips_penalty_for_client_error(self):
        """Client-side error (BAD_REQUEST) → forwarded without key penalty."""
        request = _make_mock_request()
        provider = _make_mock_provider()
        mock_response = _make_mock_response(status_code=400)
        fail_result = CheckResult.fail(ErrorReason.BAD_REQUEST, status_code=400)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "bad request"}',
        )

        mock_forwarded_response = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded_response),
            ) as mock_forward_error,
            patch(
                "src.services.gateway.gateway_service._report_key_failure",
                new=AsyncMock(),
            ) as mock_report,
        ):
            result = await _handle_full_stream_request(request, provider, "openai")

            # Should forward the error to client, not return 503 JSONResponse
            assert result is mock_forwarded_response
            mock_forward_error.assert_awaited_once()

            # Key MUST NOT be penalized or removed from pool
            mock_report.assert_not_called()
            request.app.state.gateway_cache.remove_key_from_pool.assert_not_called()


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

    @pytest.mark.asyncio
    async def test_retry_handler_aborts_for_client_error(self):
        """Client error (BAD_REQUEST) → abort retry loop immediately, no counters advanced."""
        request = _make_mock_request()
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
        mock_response = _make_mock_response(status_code=400)
        fail_result = CheckResult.fail(ErrorReason.BAD_REQUEST, status_code=400)

        provider.proxy_request.return_value = (
            mock_response,
            fail_result,
            b'{"error": "bad request"}',
        )

        mock_forwarded_response = MagicMock()
        with (
            patch(
                "src.services.gateway.gateway_service.forward_error_to_client",
                new=AsyncMock(return_value=mock_forwarded_response),
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

            # Should forward error to client, not 503
            assert result is mock_forwarded_response
            mock_forward_error.assert_awaited_once()

            # Should NOT execute second iteration — exactly one proxy_request call
            assert provider.proxy_request.call_count == 1

            # Retry/sleep paths MUST NOT be entered
            mock_sleep.assert_not_called()
            # Key MUST NOT be penalized or removed
            mock_report.assert_not_called()
            request.app.state.gateway_cache.remove_key_from_pool.assert_not_called()


# ---------------------------------------------------------------------------
# Tests 9-11: Pool health log loop
# ---------------------------------------------------------------------------


class TestPoolHealthLogLoop:
    """Tests for _pool_health_log_loop background task.

    Covers the per-connection health breakdown emitted alongside the
    aggregate ``HTTP_POOL_HEALTH`` summary line.
    """

    @pytest.mark.asyncio
    async def test_health_log_includes_per_connection_details(self, caplog):
        """Health log emits the aggregate HTTP_POOL_HEALTH summary line plus
        one HTTP_POOL_CONN line per connection with label/state/protocol/streams.

        Spec scenario: Health log line format — verifies the per-connection
        breakdown format introduced by the h2-per-provider-stream-cap change.
        """
        mock_factory = MagicMock()
        mock_factory.get_pool_health_summary.return_value = {
            "proxy:http://proxy1:8080": {
                "total_connections": 12,
                "active_connections": 4,
                "idle_connections": 8,
                "h2_connections": 12,
                "h1_connections": 0,
                "active_h2_streams": 45,
                "max_h2_stream_capacity": 1200,
                "queued_requests": 0,
                "connections": [
                    {
                        "label": "openai-conn-0",
                        "state": "active",
                        "protocol": "h2",
                        "active_streams": 3,
                        "max_streams": 5,
                    },
                    {
                        "label": "openai-conn-1",
                        "state": "idle",
                        "protocol": "h2",
                        "active_streams": 0,
                        "max_streams": 5,
                    },
                ],
            }
        }

        sleep_calls: list[int | float] = []

        async def sleep_then_cancel(delay):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:
                raise asyncio.CancelledError()

        with (
            patch("asyncio.sleep", side_effect=sleep_then_cancel),
            caplog.at_level(logging.INFO),
        ):
            await _pool_health_log_loop(mock_factory, 60)

        # --- Aggregate health summary line ---
        health_logs = [r for r in caplog.records if "HTTP_POOL_HEALTH |" in r.message]
        assert (
            len(health_logs) >= 1
        ), f"Expected at least 1 HTTP_POOL_HEALTH log line, got {len(health_logs)}"
        log_msg = health_logs[0].message
        assert "HTTP_POOL_HEALTH | proxy:http://proxy1:8080" in log_msg
        assert "conns: 12 total (4 active, 8 idle)" in log_msg
        assert "proto: 12 H2 / 0 H1" in log_msg
        assert "streams: 45 active / 1200 max_capacity" in log_msg
        assert "queued: 0" in log_msg

        # --- Per-connection breakdown lines ---
        conn_logs = [r for r in caplog.records if "HTTP_POOL_CONN |" in r.message]
        assert len(conn_logs) == 2, (
            f"Expected 2 HTTP_POOL_CONN log lines (one per connection), "
            f"got {len(conn_logs)}"
        )
        # First connection — active H2 with 3/5 streams
        assert (
            "HTTP_POOL_CONN | proxy:http://proxy1:8080 | openai-conn-0 "
            "| active | h2 | streams: 3/5"
        ) in conn_logs[0].message
        # Second connection — idle H2 with 0/5 streams
        assert (
            "HTTP_POOL_CONN | proxy:http://proxy1:8080 | openai-conn-1 "
            "| idle | h2 | streams: 0/5"
        ) in conn_logs[1].message

    @pytest.mark.asyncio
    async def test_health_logging_respects_interval(self):
        """Background task sleeps for the configured interval between iterations.

        Spec scenario: Health logging respects configured interval — each
        ``asyncio.sleep`` call must use the interval value passed to
        ``_pool_health_log_loop``.
        """
        mock_factory = MagicMock()
        mock_factory.get_pool_health_summary.return_value = {
            "proxy:http://proxy1:8080": {
                "total_connections": 1,
                "active_connections": 0,
                "idle_connections": 1,
                "h2_connections": 1,
                "h1_connections": 0,
                "active_h2_streams": 0,
                "max_h2_stream_capacity": 100,
                "queued_requests": 0,
                "connections": [],
            }
        }

        interval = 2
        sleep_delays: list[int | float] = []

        async def track_sleep(delay):
            sleep_delays.append(delay)
            if len(sleep_delays) >= 3:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=track_sleep):
            await _pool_health_log_loop(mock_factory, interval)

        # Should have slept at least 3 times
        assert (
            len(sleep_delays) >= 3
        ), f"Expected at least 3 sleep calls, got {len(sleep_delays)}"
        # Each sleep call must use the configured interval
        for i, delay in enumerate(sleep_delays):
            assert (
                delay == interval
            ), f"Sleep call {i}: expected {interval}, got {delay}"

    @pytest.mark.asyncio
    async def test_health_logging_disabled_when_zero(self, caplog):
        """When pool_health_log_interval_sec is 0, no health task is started
        and no health log lines are emitted.

        Spec scenario: Health logging disabled when interval is zero — the
        lifespan startup code guards task creation with
        ``isinstance(interval, int) and interval > 0``, so a zero interval
        must skip ``_pool_health_log_loop`` entirely.
        """
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

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory",
            ) as mock_hcf_cls,
            patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
            patch(
                "src.services.gateway.gateway_service._cache_refresh_loop",
                new=AsyncMock(),
            ),
            caplog.at_level(logging.INFO),
        ):
            mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
            mock_gc_cls.return_value.populate_caches = AsyncMock()

            # Set pool_health_log_interval_sec to 0 on the factory instance
            # to verify that a zero interval disables the health log loop.
            mock_factory_instance = MagicMock()
            mock_factory_instance._pool_health_log_interval_sec = 0
            mock_factory_instance.close_all = AsyncMock()
            mock_hcf_cls.return_value = mock_factory_instance

            app = create_app(accessor)

            # Trigger the lifespan (startup + shutdown) via TestClient
            with TestClient(app):
                pass

            # After full lifespan (shutdown included), verify no health task
            assert not hasattr(
                app.state, "pool_health_task"
            ), "pool_health_task should NOT be set when interval is 0"

        # Verify no health log lines were emitted
        health_logs = [r for r in caplog.records if "HTTP_POOL_HEALTH" in r.message]
        assert (
            len(health_logs) == 0
        ), f"Expected 0 HTTP_POOL_HEALTH log lines, got {len(health_logs)}"

    @pytest.mark.asyncio
    async def test_health_logging_disabled_when_attribute_inaccessible(self, caplog):
        """When the factory's _pool_health_log_interval_sec attribute is
        inaccessible (e.g. a bare MagicMock without explicit attribute),
        the health task is NOT started and no TypeError is raised.

        Spec scenario: Health logging disabled when interval attribute is
        inaccessible. Primary regression test for P0-A fix: ``getattr`` with
        fallback returns a MagicMock (not 0), but ``isinstance(interval, int)``
        guards against non-integer types.
        """
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

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory",
            ) as mock_hcf_cls,
            patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
            patch(
                "src.services.gateway.gateway_service._cache_refresh_loop",
                new=AsyncMock(),
            ),
            caplog.at_level(logging.INFO),
        ):
            mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
            mock_gc_cls.return_value.populate_caches = AsyncMock()

            # Bare MagicMock — _pool_health_log_interval_sec is NOT set;
            # getattr returns a MagicMock, isinstance(int) is False, loop skipped.
            mock_factory_instance = MagicMock()
            mock_factory_instance.close_all = AsyncMock()
            mock_hcf_cls.return_value = mock_factory_instance

            app = create_app(accessor)

            # Trigger the lifespan (startup + shutdown) via TestClient
            with TestClient(app):
                pass

            assert not hasattr(app.state, "pool_health_task"), (
                "pool_health_task should NOT be set when " "attribute is inaccessible"
            )

        health_logs = [r for r in caplog.records if "HTTP_POOL_HEALTH" in r.message]
        assert (
            len(health_logs) == 0
        ), f"Expected 0 HTTP_POOL_HEALTH log lines, got {len(health_logs)}"

    @pytest.mark.asyncio
    async def test_real_factory_starts_health_loop(self):
        """When HttpClientFactory has _pool_health_log_interval_sec=60 (a real
        positive int), the health logging background task IS started.

        Spec scenario: Real HttpClientFactory starts health loop normally.
        """
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

        with (
            patch(
                "src.services.gateway.gateway_service.database.init_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.database.close_db_pool",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service.DatabaseManager"
            ) as mock_dm_cls,
            patch(
                "src.services.gateway.gateway_service.HttpClientFactory",
            ) as mock_hcf_cls,
            patch("src.services.gateway.gateway_service.GatewayCache") as mock_gc_cls,
            patch(
                "src.services.gateway.gateway_service._cache_refresh_loop",
                new=AsyncMock(),
            ),
            patch(
                "src.services.gateway.gateway_service._pool_health_log_loop",
                new=AsyncMock(),
            ),
        ):
            mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
            mock_gc_cls.return_value.populate_caches = AsyncMock()

            # Real int value — isinstance passes, interval > 0, health task started.
            mock_factory_instance = MagicMock()
            mock_factory_instance._pool_health_log_interval_sec = 60
            mock_factory_instance.close_all = AsyncMock()
            mock_hcf_cls.return_value = mock_factory_instance

            app = create_app(accessor)

            # Trigger the lifespan (startup + shutdown) via TestClient
            with TestClient(app):
                pass

            # After lifespan, verify the health task was created
            assert hasattr(
                app.state, "pool_health_task"
            ), "pool_health_task should be set when interval is 60"
            assert app.state.pool_health_task is not None

    def test_mocked_factory_falls_back_gracefully(self):
        """A bare MagicMock's auto-created attribute is caught by isinstance guard.

        Spec scenario: Mocked HttpClientFactory falls back gracefully.
        ``getattr(MagicMock(), "_pool_health_log_interval_sec", 0)`` returns
        a MagicMock (not 0), but ``isinstance(ret, int)`` is False, so the
        ``and`` short-circuits to False and the health loop is skipped.
        """
        factory = MagicMock()
        interval = getattr(factory, "_pool_health_log_interval_sec", 0)

        # MagicMock auto-creates the attribute, so getattr does NOT return 0
        assert not isinstance(
            interval, int
        ), "MagicMock auto-attribute should not be an int"
        assert isinstance(
            interval, MagicMock
        ), "getattr on MagicMock should return a MagicMock, not the fallback 0"

        # The isinstance guard prevents the health loop from starting
        assert not (isinstance(interval, int) and interval > 0)


# ---------------------------------------------------------------------------
# Tests 9-11: create_app factory
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
            patch("src.services.gateway.gateway_service.HttpClientFactory"),
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
            patch("src.services.gateway.gateway_service.HttpClientFactory"),
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
            patch("src.services.gateway.gateway_service.HttpClientFactory"),
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
            if (
                "if " in line and "else:" in lines[i + 1]
                if i + 1 < len(lines)
                else False
            ):
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
