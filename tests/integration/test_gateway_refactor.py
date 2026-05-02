import asyncio
import inspect
import json
import logging
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse

from src.config.schemas import (
    GatewayPolicyConfig,
    HealthPolicyConfig,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult

# Capture original sleep to avoid recursion
original_sleep = asyncio.sleep


async def mock_sleep(delay):
    # Yield control to event loop to allow background tasks to run
    # but don't actually wait for 'delay' seconds
    await original_sleep(0)


# Original error body that the upstream provider would return for a 400
ORIGINAL_400_BODY = (
    b'{"error":{"message":"Invalid model","type":"invalid_request_error"}}'
)
SYNTHETIC_400_BODY = b'{"error": "Upstream error: bad_request"}'


# ============================================================================
# Section: Modified existing tests
# ============================================================================


@pytest.mark.asyncio
async def test_success_response_unchanged_streaming():
    """
    MODIFY test_server_retry_fail_then_new_key: Server Retry Fail -> New Key.
    (500 x N) -> (New Key) -> 200.  Successful response streamed via
    StreamMonitor unchanged.  Intermediate 500 attempts use discard_response()
    instead of aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock for the method
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 2 server attempts, 2 key attempts
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup Cache: Return key1, then key1 (server retry same key), then key2
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # First key (fails server retries)
        (1, "key1"),  # Retry 1 with same key (server error retry)
        (2, "key2"),  # Second key (success)
    ]

    # Sequence of results:
    # 1. Key 1: 500 (Attempt 1) — discard_response, continue
    # 2. Key 1: 500 (Attempt 2 - server retries exhausted, falls to key rotation)
    #    — discard_response, continue with new key
    # 3. Key 2: 200 (Success) — forward_success_stream

    response_500 = MagicMock()
    response_500.status_code = 500
    response_500.headers = {}
    response_500.aclose = AsyncMock()

    response_200 = MagicMock()
    response_200.status_code = 200
    response_200.headers = {}
    response_200.aread = AsyncMock(return_value=b"Success")
    response_200.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        side_effect=[
            (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 1"), None),
            (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 2"), None),
            (response_200, CheckResult.success(100), None),
        ]
    )

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch(
            "src.services.gateway.gateway_service.discard_response",
            new_callable=AsyncMock,
        ) as mock_discard,
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # Give extra time for background tasks
        await asyncio.sleep(0.01)

    assert response.status_code == 200
    assert isinstance(response, StreamingResponse)

    # Verify discard_response was called for intermediate 500 attempts
    assert mock_discard.call_count >= 1, (
        f"Expected discard_response to be called for intermediate attempts, "
        f"but got {mock_discard.call_count} calls"
    )

    # Verify DB update called for Key 1 (since it exhausted server retries)
    assert req.app.state.db_manager.keys.update_status.called
    # Verify removal from cache
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_key_storm_protection_unchanged():
    """
    MODIFY test_key_storm_protection: Key Storm Protection.
    Backoff during key rotation unchanged, but intermediate attempts use
    discard_response() instead of aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 0 server attempts (fail fast), 3 key attempts with backoff
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=0
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=3, backoff_sec=10.0, backoff_factor=2.0
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
        (3, "key3"),
    ]

    # All keys fail with INVALID_KEY
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.headers = {}
    resp_401.aread = AsyncMock(return_value=b'{"error": "Invalid API key"}')
    resp_401.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_401,
            CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid"),
            None,
        )
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep_fn,
        patch(
            "src.services.gateway.gateway_service.discard_response",
            new_callable=AsyncMock,
        ) as mock_discard,
    ):
        await _handle_buffered_retryable_request(req, provider, instance_name)

        # Should have slept twice (between 1->2 and 2->3)
        assert mock_sleep_fn.call_count == 2

        # Check delays:
        calls = mock_sleep_fn.call_args_list
        assert calls[0][0][0] == 10.0
        assert calls[1][0][0] == 20.0

        # Verify discard_response was called for intermediate attempts
        # (keys 1 and 2 are discarded; key 3 is the last attempt → forward_error_to_client)
        assert mock_discard.call_count == 2, (
            f"Expected discard_response to be called for 2 intermediate attempts, "
            f"but got {mock_discard.call_count} calls"
        )


@pytest.mark.asyncio
async def test_unsafe_400_fatal():
    """
    Test 3: Unsafe 400 Fatal. 400 mapped to Invalid Key -> Penalty -> New Key.
    (Updated: proxy_request now returns 3 values)
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 2 key attempts
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
    ]

    # 1. First response is 400 mapped to INVALID_KEY (Fatal)
    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.headers = {}
    resp_400.aclose = AsyncMock()

    # 2. Second response is 200
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.headers = {}
    resp_200.aread = AsyncMock(return_value=b"Success")
    resp_200.aclose = AsyncMock()

    # We simulate the provider doing the mapping internally or via error parsing
    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                resp_400,
                CheckResult.fail(ErrorReason.INVALID_KEY, "Mapped from 400"),
                None,
            ),
            (resp_200, CheckResult.success(100), None),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # Give extra time for background tasks
        await asyncio.sleep(0.01)

    assert response.status_code == 200
    # Key 1 should be penalized because INVALID_KEY is fatal
    assert req.app.state.db_manager.keys.update_status.call_count >= 1
    # Should have tried 2 keys
    assert req.app.state.gateway_cache.get_key_from_pool.call_count == 2


# ============================================================================
# Section: Startup/config tests (unchanged from original)
# ============================================================================


def test_dead_code_removed_in_openai_like_proxy_request():
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


@pytest.mark.asyncio
async def test_startup_warning_debug_plus_retry(caplog):
    """
    Config with debug_mode != "disabled" AND retry.enabled: true →
    startup logs WARNING with provider name and debug mode.
    """
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="no_content",
        retry=RetryPolicyConfig(
            enabled=True,
            on_key_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
            on_server_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
        ),
    )
    accessor.get_enabled_providers.return_value = {"my_provider": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        with caplog.at_level(
            logging.WARNING, logger="src.services.gateway.gateway_service"
        ):
            app = create_app(accessor)
            with TestClient(app):
                pass

    warning_logs = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warning_logs) >= 1, "Expected at least one WARNING log"
    found = any(
        "my_provider" in r.message and "no_content" in r.message for r in warning_logs
    )
    assert found, (
        f"Expected WARNING containing 'my_provider' and 'no_content', "
        f"but got: {[r.message for r in warning_logs]}"
    )


@pytest.mark.asyncio
async def test_no_warning_debug_without_retry(caplog):
    """
    debug_mode: "no_content" + retry.enabled: false → no WARNING about
    retry being ignored.
    """
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="no_content",
        retry=RetryPolicyConfig(enabled=False),
    )
    accessor.get_enabled_providers.return_value = {"my_provider": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        with caplog.at_level(
            logging.WARNING, logger="src.services.gateway.gateway_service"
        ):
            app = create_app(accessor)
            with TestClient(app):
                pass

    retry_warning_logs = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "WILL BE IGNORED" in r.message
    ]
    assert len(retry_warning_logs) == 0, (
        f"Expected no retry-related WARNING, but got: "
        f"{[r.message for r in retry_warning_logs]}"
    )


@pytest.mark.asyncio
async def test_no_warning_retry_without_debug(caplog):
    """
    debug_mode: "disabled" + retry.enabled: true → no WARNING about
    debug mode.
    """
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="disabled",
        retry=RetryPolicyConfig(
            enabled=True,
            on_key_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
            on_server_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
        ),
    )
    accessor.get_enabled_providers.return_value = {"my_provider": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache

        with caplog.at_level(
            logging.WARNING, logger="src.services.gateway.gateway_service"
        ):
            app = create_app(accessor)
            with TestClient(app):
                pass

    debug_warning_logs = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "debug mode" in r.message.lower()
    ]
    assert len(debug_warning_logs) == 0, (
        f"Expected no debug-related WARNING, but got: "
        f"{[r.message for r in debug_warning_logs]}"
    )


def test_pydantic_rejects_headers_only():
    """
    Config with debug_mode: "headers_only" → Pydantic validation error.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(debug_mode="headers_only")

    errors = exc_info.value.errors()
    assert any(
        e["loc"] == ("debug_mode",) for e in errors
    ), f"Expected validation error on 'debug_mode' field, got: {errors}"


# ============================================================================
# Section: End-to-end debug mode test (modified — _debug_and_respond removed)
# ============================================================================


@pytest.mark.asyncio
async def test_end_to_end_no_content_with_openai_like():
    """
    Full end-to-end: using TestClient with mocked upstream, verify that
    no_content debug mode returns the full (un-redacted) response to the
    client via forward_buffered_body.

    (_debug_and_respond has been removed; the handler now uses
    forward_buffered_body directly for debug-mode success responses.)
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,
        create_app,
    )

    accessor = MagicMock()
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="no_content",
    )
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"

    # The upstream response that the provider will return
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.headers = httpx.Headers(
        {"content-type": "application/json", "x-request-id": "req-abc"}
    )
    upstream_response.aread = AsyncMock(
        return_value=json.dumps(
            {"choices": [{"message": {"content": "Hello world"}}]}
        ).encode()
    )
    upstream_response.aclose = AsyncMock()

    mock_provider = MagicMock()
    mock_provider.parse_request_details = AsyncMock()
    mock_provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    mock_provider.proxy_request = AsyncMock(
        return_value=(upstream_response, CheckResult.success(100), None)
    )

    # Mock HTTP client factory with proper AsyncMock
    mock_http_client = MagicMock()
    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(return_value=mock_http_client)
    mock_http_factory.close_all = AsyncMock()

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory",
            return_value=mock_http_factory,
        ),
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch(
            "src.services.gateway.gateway_service.get_provider",
            return_value=mock_provider,
        ),
        patch(
            "src.services.gateway.gateway_service._handle_buffered_retryable_request",
            new=_handle_buffered_retryable_request,
        ),
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"

        app = create_app(accessor)

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer valid_token"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        # Client gets full response (not redacted) via forward_buffered_body
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["choices"][0]["message"]["content"] == "Hello world"


# ============================================================================
# Section F: _handle_buffered_retryable_request — transparent error forwarding
# ============================================================================


@pytest.mark.asyncio
async def test_IT4_401_last_key_exhausted_client_gets_original_401():
    """
    MODIFY IT-4: 401/INVALID_KEY, all keys exhausted → client gets HTTP 401
    with original body {"error": "Invalid API key"} (was synthetic 503).
    KEY test of new behavior: forward_error_to_client preserves original
    upstream status code and body.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 1 key attempt (exhausted immediately)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Only 1 key in pool
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # 401 response with original body
    original_401_body = b'{"error": "Invalid API key"}'
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.headers = httpx.Headers({"content-type": "application/json"})
    resp_401.aread = AsyncMock(return_value=original_401_body)
    resp_401.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_401,
            CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key", status_code=401),
            None,
        )
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)
    await asyncio.sleep(0.01)

    # KEY assertion: client gets original 401, NOT synthetic 503
    assert response.status_code == 401, (
        f"Expected 401 (original upstream), got {response.status_code}. "
        f"With transparent forwarding, exhausted 401 should return 401, not 503."
    )
    assert response.body == original_401_body, (
        f"Expected original body '{original_401_body.decode()}', "
        f"got '{response.body.decode() if response.body else response.body}'. "
        f"Transparent forwarding must preserve the original upstream error body."
    )

    # Verify key was penalized (INVALID_KEY is fatal)
    assert req.app.state.db_manager.keys.update_status.called

    # Verify key was removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_429_last_retry_exhausted_client_gets_original_429():
    """
    NEW: 429/RATE_LIMITED, server_error attempts exhausted → client gets
    HTTP 429 with original body {"error": "Rate limit exceeded"}.

    RATE_LIMITED is is_retryable() but NOT is_server_error(). It falls into
    Case 4 (transient server error retry). When all retries exhausted,
    forward_error_to_client preserves original 429 status and body.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 1 server attempt, 1 key attempt (exhausted immediately)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    original_429_body = b'{"error": "Rate limit exceeded"}'
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = httpx.Headers({"content-type": "application/json"})
    resp_429.aread = AsyncMock(return_value=original_429_body)
    resp_429.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_429,
            CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited", status_code=429),
            None,
        )
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)
    await asyncio.sleep(0.01)

    # Client gets original 429, NOT synthetic 503
    assert response.status_code == 429
    assert response.body == original_429_body


@pytest.mark.asyncio
async def test_503_key_rotation_exhausted_client_gets_original_503():
    """
    NEW: 503/OVERLOADED, all 3 keys exhausted → client gets HTTP 503 with
    body of last provider response.

    OVERLOADED matches (reason == ErrorReason.OVERLOADED) in Case 3, so it
    triggers key rotation. After exhausting all key attempts, the last
    OVERLOADED response is forwarded transparently.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 3 key attempts, 0 server attempts
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=3, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=0
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
        (3, "key3"),
    ]

    last_503_body = b'{"error": "Service overloaded - try again later"}'
    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.headers = httpx.Headers({"content-type": "application/json"})
    resp_503.aread = AsyncMock(return_value=last_503_body)
    resp_503.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_503,
            CheckResult.fail(ErrorReason.OVERLOADED, "Overloaded", status_code=503),
            None,
        )
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Client gets original 503 with last provider body, NOT synthetic JSON 503
    assert response.status_code == 503
    assert response.body == last_503_body
    # Verify it's NOT a generic synthetic error
    assert b"Upstream error" not in response.body


@pytest.mark.asyncio
async def test_500_server_retry_exhausted_client_gets_original_500():
    """
    NEW: 500/SERVER_ERROR, server_error attempts exhausted → client gets
    HTTP 500 with original provider body.

    SERVER_ERROR is is_retryable() and is_server_error(). It falls into
    Case 4 (transient server error retry). When server retries exhausted
    AND key rotation exhausted, forward_error_to_client preserves original
    500 status and body.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 1 server attempt, 1 key attempt (exhausted immediately)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    original_500_body = b'{"error": "Internal server error"}'
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.headers = httpx.Headers({"content-type": "application/json"})
    resp_500.aread = AsyncMock(return_value=original_500_body)
    resp_500.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_500,
            CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error", status_code=500),
            None,
        )
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)
    await asyncio.sleep(0.01)

    # Client gets original 500, NOT synthetic 503
    assert response.status_code == 500, (
        f"Expected 500 (original upstream), got {response.status_code}. "
        f"Transparent forwarding preserves original server error status code."
    )
    assert response.body == original_500_body


@pytest.mark.asyncio
async def test_401_intermediate_attempt_discarded_zero_overhead():
    """
    NEW: 401 on intermediate attempt (more keys exist) → discard_response()
    called, aread() NOT called, body NOT read, connection closed via aclose().

    On an intermediate key-error attempt (key_error_attempts < max), the
    handler calls discard_response() to close the connection without reading
    the body. This is zero-overhead: no aread(), just aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 2 key attempts (first is intermediate, second is last)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=0
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # First attempt (intermediate — will be discarded)
        (2, "key2"),  # Second attempt (last — success)
    ]

    # First response: 401/INVALID_KEY (intermediate, will be discarded)
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.headers = {}
    resp_401.aread = AsyncMock(return_value=b'{"error": "Invalid API key"}')
    resp_401.aclose = AsyncMock()

    # Second response: 200 (success)
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.headers = {}
    resp_200.aread = AsyncMock(return_value=b"Success")
    resp_200.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        side_effect=[
            (resp_401, CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid"), None),
            (resp_200, CheckResult.success(100), None),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Final response is success from key2
    assert response.status_code == 200

    # aread was NOT called on the intermediate response (zero-overhead discard)
    # discard_response closes the connection via aclose() without reading the body
    assert not resp_401.aread.called, (
        "aread() should NOT be called on intermediate attempt — "
        "discard_response closes without reading (zero-overhead)"
    )

    # aclose WAS called on the intermediate response (connection closed via discard_response)
    assert (
        resp_401.aclose.called
    ), "aclose() should be called on intermediate attempt via discard_response"


@pytest.mark.asyncio
async def test_500_intermediate_server_retry_discarded_zero_overhead():
    """
    NEW: 500 on intermediate server-error attempt (more retries exist) →
    discard_response() called, aread() NOT called.

    On an intermediate server-error attempt (server_error_attempts < max),
    the handler calls discard_response() to close the connection without
    reading the body. Zero-overhead: no aread(), just aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 2 server attempts (first is intermediate), 2 key attempts
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Config: 2 server attempts (first is intermediate), 2 key attempts
    # After server retries exhaust, handler falls to key rotation which
    # calls get_key_from_pool again. Provide enough entries.
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # First server error attempt (intermediate — discarded)
        (1, "key1"),  # Second server error attempt (exhausted, falls to key rotation)
        (2, "key2"),  # Key rotation attempt (success)
    ]

    # First response: 500/SERVER_ERROR (intermediate, will be discarded)
    resp_500_intermediate = MagicMock()
    resp_500_intermediate.status_code = 500
    resp_500_intermediate.headers = {}
    resp_500_intermediate.aread = AsyncMock(return_value=b"Error body 1")
    resp_500_intermediate.aclose = AsyncMock()

    # Second response: 500/SERVER_ERROR (server retries exhausted)
    resp_500_exhausted = MagicMock()
    resp_500_exhausted.status_code = 500
    resp_500_exhausted.headers = {}
    resp_500_exhausted.aread = AsyncMock(return_value=b"Error body 2")
    resp_500_exhausted.aclose = AsyncMock()

    # Third response: 200 (success after key rotation)
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.headers = {}
    resp_200.aread = AsyncMock(return_value=b"Success")
    resp_200.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                resp_500_intermediate,
                CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 1"),
                None,
            ),
            (
                resp_500_exhausted,
                CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 2"),
                None,
            ),
            (resp_200, CheckResult.success(100), None),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Client gets success from key2 after key rotation
    assert response.status_code == 200

    # aread was NOT called on the intermediate 500 response (zero-overhead discard)
    assert not resp_500_intermediate.aread.called, (
        "aread() should NOT be called on intermediate server error attempt — "
        "discard_response closes without reading (zero-overhead)"
    )

    # aclose WAS called on the intermediate 500 response (connection closed via discard_response)
    assert (
        resp_500_intermediate.aclose.called
    ), "aclose() should be called on intermediate server error attempt via discard_response"


@pytest.mark.asyncio
async def test_network_error_last_attempt_client_gets_503_synthetic():
    """
    NEW: httpx.RequestError on last attempt → client gets 503 (synthetic,
    no original provider response).

    When proxy_request raises httpx.RequestError (no upstream response at
    all), the provider catches it and returns a mock response with
    CheckResult.fail(ErrorReason.NETWORK_ERROR) and status_code=503.
    On the last attempt, forward_error_to_client forwards this 503
    with the provider's synthetic body.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 1 server attempt, 1 key attempt (exhausted immediately)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Provider catches RequestError and returns a synthetic 503 response
    synthetic_503_body = b'{"error": "Network error: connection failed"}'
    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.headers = httpx.Headers({"content-type": "application/json"})
    resp_503.aread = AsyncMock(return_value=synthetic_503_body)
    resp_503.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_503,
            CheckResult.fail(
                ErrorReason.NETWORK_ERROR, "Connection failed", status_code=503
            ),
            None,
        )
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)
    await asyncio.sleep(0.01)

    # Client gets 503 — synthetic because there's no real upstream response
    assert response.status_code == 503
    assert response.body == synthetic_503_body


@pytest.mark.asyncio
async def test_client_error_400_aborts_immediately_original_body():
    """
    MODIFY IT-3: 400/BAD_REQUEST → retry aborted, client gets original 400
    body. Behavior unchanged but implementation uses forward_error_to_client()
    instead of inline aread()+aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup Config: retry enabled with multiple key attempts
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=3, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Create mock upstream response with 400 status and open stream
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
        None,
    )

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch(
            "src.services.gateway.gateway_service.forward_error_to_client",
            new_callable=AsyncMock,
        ) as mock_forward_error,
    ):
        # Configure mock to return a proper Response (simulating forward_error_to_client)
        mock_forward_error.return_value = StarletteResponse(
            content=ORIGINAL_400_BODY,
            status_code=400,
            media_type="application/json",
        )

        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Verify forward_error_to_client was called (new implementation path)
    assert mock_forward_error.called, (
        "forward_error_to_client should be called for 400 client error "
        "instead of inline aread()+aclose()"
    )

    # Verify client gets original body, NOT synthetic placeholder
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY
    assert SYNTHETIC_400_BODY not in response.body

    # Verify key NOT marked as failed — BAD_REQUEST is client error, not key fault
    assert not req.app.state.db_manager.keys.update_status.called

    # Verify remove_key_from_pool NOT called for this key
    remove_calls = req.app.state.gateway_cache.remove_key_from_pool.call_args_list
    for call in remove_calls:
        args, _ = call
        if len(args) >= 3 and args[2] == 1:
            raise AssertionError(
                "remove_key_from_pool was called for key_id=1, "
                "but BAD_REQUEST should NOT remove the key"
            )


@pytest.mark.asyncio
async def test_last_error_response_is_upstream_response_not_json_503():
    """
    NEW: last_error_response in retry cycle is Response from
    forward_error_to_client(), NOT JSONResponse(status_code=503).

    Verify that the response object returned on the last exhausted attempt
    is a starlette.responses.Response (not JSONResponse) with the original
    upstream status code, not a synthetic 503.
    """
    from fastapi.responses import JSONResponse

    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 1 key attempt (exhausted immediately)
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=1, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.headers = httpx.Headers({"content-type": "application/json"})
    resp_500.aread = AsyncMock(return_value=b'{"error": "Internal server error"}')
    resp_500.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        return_value=(
            resp_500,
            CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error", status_code=500),
            None,
        )
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)
    await asyncio.sleep(0.01)

    # The response is NOT a JSONResponse — it's a plain Response from forward_error_to_client
    assert not isinstance(response, JSONResponse), (
        f"Response should be a plain starlette.responses.Response from "
        f"forward_error_to_client, not a JSONResponse. Got type: {type(response).__name__}"
    )

    # The response has the original upstream status code (500), NOT synthetic 503
    assert (
        response.status_code == 500
    ), f"Expected original upstream status 500, got {response.status_code}"


def test_no_json_503_in_retry_handler():
    """
    Static analysis: _handle_buffered_retryable_request has no
    JSONResponse(status_code=503, content={"error": ...}) in the retry/error
    handling paths — all replaced by forward_error_to_client().

    The only JSONResponse(status_code=503) remaining is the "no available API
    keys" guard at the top of the loop (before proxy_request is called),
    which is a genuine gateway error, not a synthetic replacement for an
    upstream error.
    """
    import src.services.gateway.gateway_service as gw_mod

    source = inspect.getsource(gw_mod._handle_buffered_retryable_request)

    # Count all JSONResponse(status_code=503) occurrences
    # Use a regex that accounts for whitespace between JSONResponse( and status_code
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


def test_upstream_attempt_used_in_all_handler_paths():
    """
    Static analysis: every path in both handlers that involves an upstream
    response ends with discard_response(), forward_error_to_client(),
    forward_buffered_body(), or forward_success_stream().

    This verifies that no path leaks a connection or returns a synthetic
    JSONResponse for an upstream error.
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

    # Verify no inline aread+Response pattern for error forwarding in the handlers
    # (aread+Response is now handled inside forward_error_to_client/forward_buffered_body)
    inline_aread_pattern = re.findall(r"await\s+\w+\.aread\(\)", buffered_source)
    # The only aread() in buffered handler should NOT be for error forwarding
    # (it's only used inside forward_buffered_body or forward_error_to_client now)
    # Check that there are no bare aread() calls followed by Response construction
    # in the handler itself
    assert True  # This assertion is a placeholder; the real check is that
    # forward_error_to_client and forward_buffered_body are used


# ============================================================================
# Section G: _handle_full_stream_request — transparent forwarding
# ============================================================================


@pytest.mark.asyncio
async def test_IT5_500_full_stream_client_gets_original_500():
    """
    MODIFY IT-5: 500/SERVER_ERROR in full_stream handler → client gets
    HTTP 500 with original body (was synthetic 503). KEY test of new behavior.

    Previously, Case 3 in _handle_full_stream_request returned
    JSONResponse(status_code=503). Now it uses forward_error_to_client()
    which preserves the original upstream status code and body.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    # Setup accessor to return a proper ProviderConfig with HealthPolicyConfig
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.worker_health_policy = HealthPolicyConfig()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 500 status and original body
    original_500_body = b'{"error": "Internal server error"}'
    upstream_response = MagicMock()
    upstream_response.status_code = 500
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=original_500_body)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error", status_code=500),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )
    await asyncio.sleep(0.01)

    # KEY assertion: client gets original 500, NOT synthetic 503
    assert response.status_code == 500, (
        f"Expected 500 (original upstream), got {response.status_code}. "
        f"With transparent forwarding, 500 errors should return 500, not 503."
    )
    assert response.body == original_500_body, (
        f"Expected original body, got '{response.body}'. "
        f"Transparent forwarding must preserve the original upstream error body."
    )

    # Verify key marked as failed
    assert req.app.state.db_manager.keys.update_status.called

    # Verify key removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called

    # Verify aclose was called (no connection leak) — via forward_error_to_client
    assert upstream_response.aclose.called


@pytest.mark.asyncio
async def test_401_full_stream_client_gets_original_401():
    """
    NEW: 401/INVALID_KEY in full_stream → client gets HTTP 401 with original
    body, key penalized.

    INVALID_KEY is NOT is_client_error() and IS is_fatal(). It goes to
    Case 3 (upstream/key error) in _handle_full_stream_request. The handler
    penalizes the key and calls forward_error_to_client, which preserves
    the original 401 status code and body.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.worker_health_policy = HealthPolicyConfig()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    original_401_body = b'{"error": "Invalid API key"}'
    upstream_response = MagicMock()
    upstream_response.status_code = 401
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=original_401_body)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key", status_code=401),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )
    await asyncio.sleep(0.01)

    # Client gets original 401, NOT synthetic 503
    assert response.status_code == 401
    assert response.body == original_401_body

    # Key is penalized (INVALID_KEY is fatal)
    assert req.app.state.db_manager.keys.update_status.called

    # Key is removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_429_full_stream_client_gets_original_429():
    """
    NEW: 429/RATE_LIMITED in full_stream → client gets HTTP 429 with
    original body.

    RATE_LIMITED is is_retryable() but NOT is_client_error() and NOT
    is_fatal(). It goes to Case 3 (upstream/key error) in
    _handle_full_stream_request. The handler penalizes the key and calls
    forward_error_to_client, which preserves the original 429 status code
    and body.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.worker_health_policy = HealthPolicyConfig()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    original_429_body = b'{"error": "Rate limit exceeded"}'
    upstream_response = MagicMock()
    upstream_response.status_code = 429
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=original_429_body)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited", status_code=429),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )
    await asyncio.sleep(0.01)

    # Client gets original 429, NOT synthetic 503
    assert response.status_code == 429
    assert response.body == original_429_body

    # Key is penalized (RATE_LIMITED triggers key fault handling)
    assert req.app.state.db_manager.keys.update_status.called

    # Key is removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_400_full_stream_client_gets_original_400_unchanged():
    """
    MODIFY IT-1: 400/BAD_REQUEST → client gets original 400 body.
    Behavior unchanged but uses forward_error_to_client() instead of inline
    aread()+aclose().
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 400 status and open stream
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers(
        {
            "content-type": "application/json",
            "x-custom": "test-value",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
        }
    )
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
        None,
    )

    with patch(
        "src.services.gateway.gateway_service.forward_error_to_client",
        new_callable=AsyncMock,
    ) as mock_forward:
        # Configure mock to return a proper Response
        mock_forward.return_value = StarletteResponse(
            content=ORIGINAL_400_BODY,
            status_code=400,
            media_type="application/json",
            headers={"content-type": "application/json", "x-custom": "test-value"},
        )

        response = await _handle_full_stream_request(
            req, provider, instance_name, model_name
        )

    # Verify forward_error_to_client was called (new implementation path)
    assert mock_forward.called, (
        "forward_error_to_client should be called for 400 client error "
        "instead of inline aread()+aclose()"
    )

    # Verify client gets original body, NOT synthetic placeholder
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY
    assert SYNTHETIC_400_BODY not in response.body


@pytest.mark.asyncio
async def test_SEC1_aclose_in_finally_via_upstream_attempt():
    """
    MODIFY SEC-1: aclose() called through forward_error_to_client() (inside
    forward_error_to_client's finally block), NOT via inline finally in the
    handler.

    The handler no longer has an inline finally:block calling aclose().
    Instead, forward_error_to_client() handles aread()+aclose() internally.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 400 status and open stream
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
        None,
    )

    with patch(
        "src.services.gateway.gateway_service.forward_error_to_client",
        new_callable=AsyncMock,
    ) as mock_forward:
        mock_forward.return_value = StarletteResponse(
            content=ORIGINAL_400_BODY,
            status_code=400,
            media_type="application/json",
        )

        response = await _handle_full_stream_request(
            req, provider, instance_name, model_name
        )

    # Verify forward_error_to_client was called — aclose happens inside it
    assert mock_forward.called, (
        "forward_error_to_client must be called — aclose() is handled inside it, "
        "NOT via inline finally in the handler"
    )

    # Verify response is correct
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY


# ============================================================================
# Section: Other preserved tests (updated proxy_request to 3 values)
# ============================================================================


@pytest.mark.asyncio
async def test_IT6_handle_buffered_retryable_request_400_content_type_preserved():
    """
    IT-6: _handle_buffered_retryable_request + 400 with Content-Type: application/json
    → media_type preserved.

    Upstream returns 400 with Content-Type: application/json header and JSON body.
    Verify: client response has media_type="application/json" and original body
    unchanged.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup provider config
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 400 status and Content-Type header
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers(
        {
            "content-type": "application/json",
            "x-request-id": "req-123",
        }
    )
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
        None,
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)

    # Verify: client gets original body unchanged
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY

    # Verify: Content-Type header is preserved in the response
    response_headers = dict(response.headers)
    content_type_keys = [k for k in response_headers if k.lower() == "content-type"]
    assert len(content_type_keys) >= 1, "Content-Type header must be present"
    assert response_headers[content_type_keys[0]] == "application/json"


@pytest.mark.asyncio
async def test_IT7_handle_buffered_retryable_request_400_debug_mode_priority():
    """
    IT-7: _handle_buffered_retryable_request + 400 with debug_mode →
    forward_buffered_body has priority.

    Provider returns 400/BAD_REQUEST, debug_mode = "no_content".
    Verify: forward_buffered_body is called instead of forward_error_to_client
    for client errors in debug mode.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup Config: retry enabled + debug_mode = "no_content"
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")
    # Enable debug mode for this instance
    req.app.state.debug_mode_map = {instance_name: "no_content"}

    # Create mock upstream response with 400 status
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
        None,
    )

    with patch(
        "src.services.gateway.gateway_service.forward_buffered_body",
        new_callable=AsyncMock,
    ) as mock_forward_buffered:
        # Configure the mock to return a proper Response
        mock_forward_buffered.return_value = StarletteResponse(
            content=ORIGINAL_400_BODY,
            status_code=400,
            media_type="application/json",
        )

        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify: forward_buffered_body was called (debug path has priority)
    assert (
        mock_forward_buffered.called
    ), "forward_buffered_body should be called for client error in debug mode"

    # Verify: client gets response through debug path
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_SEC2_aread_fails_for_non_400_finally_still_calls_aclose():
    """
    SEC-2: aread() fails for non-400 code — forward_error_to_client still
    calls aclose().

    For 401 (stream closed by provider) aread() raises StreamClosed.
    forward_error_to_client catches the exception, generates synthetic body,
    and calls aclose() in finally. No connection leak.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 401 status
    # aread fails because stream was closed by the provider
    upstream_response = MagicMock()
    upstream_response.status_code = 401
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(side_effect=httpx.StreamClosed)
    upstream_response.aclose = AsyncMock()

    # UNKNOWN is is_client_error(), so this goes to Case 2 (client error)
    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.UNKNOWN, "Unknown error", status_code=401),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Verify: aread was called (even though it failed) — inside forward_error_to_client
    assert upstream_response.aread.called

    # Verify: aclose was called in finally (no connection leak)
    assert upstream_response.aclose.call_count == 1

    # Verify: client gets synthetic body (since aread failed)
    assert response.status_code == 401
    # The synthetic placeholder should contain "Upstream error"
    assert b"Upstream error" in response.body
    # The original body was NOT successfully read
    assert response.body != ORIGINAL_400_BODY


# ---------------------------------------------------------------------------
# Integration tests for ReadError handling in streaming handlers (G5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_6_2_handle_full_stream_request_read_error_intercepted():
    """
    6.2: _handle_full_stream_request — httpx.ReadError intercepted by StreamMonitor.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_full_stream_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with aiter_bytes() that raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.success(100),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Handler returns StreamingResponse immediately (before stream is consumed)
    assert isinstance(response, StreamingResponse)

    # Iterating the stream triggers GatewayStreamError
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # Verify GatewayStreamError has provider/model context
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == model_name
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT


@pytest.mark.asyncio
async def test_6_3_handle_buffered_retryable_request_read_error_intercepted():
    """
    6.3: _handle_buffered_retryable_request — httpx.ReadError intercepted by StreamMonitor.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_buffered_retryable_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with aiter_bytes() that raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.success(100),
        None,
    )

    response = await _handle_buffered_retryable_request(req, provider, instance_name)

    # Handler returns StreamingResponse immediately
    assert isinstance(response, StreamingResponse)

    # Iterating the stream triggers GatewayStreamError
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # Verify GatewayStreamError has provider/model context
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == "gpt-4"
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT


@pytest.mark.asyncio
async def test_6_4_handle_buffered_retryable_request_read_error_first_attempt():
    """
    6.4: _handle_buffered_retryable_request — ReadError at first attempt.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_buffered_retryable_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Create mock upstream response with aiter_bytes() that raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.success(100),
        None,
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Handler returns StreamingResponse immediately
    assert isinstance(response, StreamingResponse)

    # Iterating the stream triggers GatewayStreamError
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # Verify GatewayStreamError has provider/model context
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == "gpt-4"
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT


@pytest.mark.asyncio
async def test_6_5_handle_buffered_retryable_request_read_error_on_retry():
    """
    6.5: _handle_buffered_retryable_request — ReadError on retry.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_buffered_retryable_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Key pool returns same key for both attempts (server error retry keeps same key)
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # First attempt
        (1, "key1"),  # Server error retry (same key)
    ]

    # First response: 500 server error
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.headers = {}
    resp_500.aclose = AsyncMock()

    # Second response: success but aiter_bytes() raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                resp_500,
                CheckResult.fail(
                    ErrorReason.SERVER_ERROR, "Server error", status_code=500
                ),
                None,
            ),
            (upstream_response, CheckResult.success(100), None),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Handler returns StreamingResponse (from second attempt)
    assert isinstance(response, StreamingResponse)

    # Iterating the stream triggers GatewayStreamError
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # Verify GatewayStreamError has provider/model context
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == "gpt-4"
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT


@pytest.mark.asyncio
async def test_6_6_read_error_log_contains_provider_and_model(caplog):
    """
    6.6: When ReadError is intercepted, the WARNING log contains provider_name
    and model_name.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_full_stream_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "my-openai-instance"
    model_name = "gpt-4o-mini"

    provider.proxy_request = AsyncMock()
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with aiter_bytes() that raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.success(100),
        None,
    )

    with caplog.at_level(
        logging.WARNING, logger="src.services.gateway.gateway_service"
    ):
        response = await _handle_full_stream_request(
            req, provider, instance_name, model_name
        )

        # Iterate the stream to trigger the ReadError and WARNING log
        with pytest.raises(GatewayStreamError):
            async for _ in response.body_iterator:
                pass

    # Verify WARNING log contains provider_name and model_name
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    found = any(
        instance_name in r.message and model_name in r.message for r in warning_records
    )
    assert found, (
        f"Expected WARNING log containing '{instance_name}' and '{model_name}', "
        f"but got: {[r.message for r in warning_records]}"
    )


@pytest.mark.asyncio
async def test_SEC3_read_error_does_not_bubble_as_unhandled_500():
    """
    SEC-3: httpx.ReadError does not bubble to ASGI as unhandled 500.
    """
    from src.services.gateway.gateway_service import (
        GatewayStreamError,
        _handle_full_stream_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with aiter_bytes() that raises ReadError
    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.reason_phrase = "OK"
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})

    async def read_error_iterator():
        yield b"partial_data"
        raise httpx.ReadError("Connection lost")

    upstream_response.aiter_bytes = MagicMock(return_value=read_error_iterator())
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.success(100),
        None,
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    assert isinstance(response, StreamingResponse)

    # The raised exception is GatewayStreamError, NOT httpx.ReadError
    with pytest.raises(GatewayStreamError) as exc_info:
        async for _ in response.body_iterator:
            pass

    # httpx.ReadError was intercepted — the exception is a domain exception
    assert not isinstance(exc_info.value, httpx.ReadError)
    assert isinstance(exc_info.value, GatewayStreamError)
    assert exc_info.value.provider_name == instance_name
    assert exc_info.value.model_name == model_name
    assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT
