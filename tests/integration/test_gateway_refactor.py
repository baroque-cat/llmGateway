import asyncio
import inspect
import json
import logging
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse

from src.config.schemas import (
    GatewayPolicyConfig,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult


# Mock helper
def make_mock_request(url="http://test/v1/chat/completions", method="POST"):
    req = MagicMock(spec=Request)
    req.url.path = "/v1/chat/completions"
    req.url.query = ""
    req.method = method
    req.headers = {"authorization": "Bearer test-token"}
    req.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

    # Create state mock explicitly
    state = MagicMock()
    state.gateway_cache = MagicMock()
    state.gateway_cache.remove_key_from_pool = AsyncMock()

    # HTTP Factory Mock
    http_factory = MagicMock()
    http_factory.get_client_for_provider = AsyncMock(return_value=MagicMock())
    state.http_client_factory = http_factory

    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()
    state.accessor = MagicMock()
    state.debug_mode_map = {}

    req.app.state = state
    return req


# Capture original sleep to avoid recursion
original_sleep = asyncio.sleep


async def mock_sleep(delay):
    # Yield control to event loop to allow background tasks to run
    # but don't actually wait for 'delay' seconds
    await original_sleep(0)


@pytest.mark.asyncio
async def test_server_retry_fail_then_new_key():
    """
    Test 1: Server Retry Fail -> New Key. (500 x N) -> (New Key) -> 200.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock for the method
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 2 server attempts, 2 key attempts
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup Cache: Return key1, then key2
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # First key (fails server retries)
        (1, "key1"),  # Retry 1 with same key
        (2, "key2"),  # Second key (success)
    ]

    # Sequence of results:
    # 1. Key 1: 500 (Attempt 1)
    # 2. Key 1: 500 (Attempt 2 - Exhausted)
    # 3. Key 2: 200 (Success)

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
            (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 1")),
            (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 2")),
            (response_200, CheckResult.success(100)),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # Give extra time for background tasks
        await asyncio.sleep(0.01)

    assert response.status_code == 200
    assert isinstance(response, StreamingResponse)

    # Verify DB update called for Key 1 (since it exhausted server retries)
    assert req.app.state.db_manager.keys.update_status.called
    # Verify removal from cache
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_key_storm_protection():
    """
    Test 2: Key Storm Protection. Check backoff during key rotation.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 0 server attempts (fail fast), 3 key attempts with backoff
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    resp_401.aclose = AsyncMock()
    provider.proxy_request = AsyncMock(
        return_value=(resp_401, CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid"))
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep_fn:
        # We need to simulate the delay logic but NOT the wait
        # But wait, patch replaces asyncio.sleep.
        # We want to assert calls.
        await _handle_buffered_retryable_request(req, provider, instance_name)

        # Should have slept twice (between 1->2 and 2->3)
        assert mock_sleep_fn.call_count == 2

        # Check delays:
        calls = mock_sleep_fn.call_args_list
        assert calls[0][0][0] == 10.0
        assert calls[1][0][0] == 20.0


@pytest.mark.asyncio
async def test_unsafe_400_fatal():
    """
    Test 3: Unsafe 400 Fatal. 400 mapped to Invalid Key -> Penalty -> New Key.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config: 2 key attempts
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    # Here we just return the result that implies the mapping happened
    provider.proxy_request = AsyncMock(
        side_effect=[
            (resp_400, CheckResult.fail(ErrorReason.INVALID_KEY, "Mapped from 400")),
            (resp_200, CheckResult.success(100)),
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


# ---------------------------------------------------------------------------
# NEW: Refactor-related tests for the refactor-debug-modes change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_and_respond_exists_and_used_at_5_sites():
    """
    Static analysis / code review test: verify that gateway_service.py
    defines the _debug_and_respond function and that the 5 handler locations
    that previously had inline debug blocks now call it.
    """
    import src.services.gateway_service as gw_mod

    # 1. Verify the function exists and is async
    func = getattr(gw_mod, "_debug_and_respond", None)
    assert func is not None, "_debug_and_respond must exist in gateway_service.py"
    assert inspect.iscoroutinefunction(func), "_debug_and_respond must be async"

    # 2. Count the call sites in the source code
    source = inspect.getsource(gw_mod)
    call_count = len(re.findall(r"_debug_and_respond\(", source))
    # The definition itself counts as 1 match, so call sites = total - 1
    assert call_count >= 6, (
        f"Expected at least 5 call sites + 1 definition = 6 occurrences, "
        f"but found {call_count}. The inline debug blocks should be replaced "
        f"by calls to _debug_and_respond."
    )


@pytest.mark.asyncio
async def test_debug_and_respond_pre_sanitizes_body():
    """
    Verify that _debug_and_respond pre-sanitizes the body before passing it
    to _log_debug_info. In no_content mode, redact_content() should be applied
    before logging, so _log_debug_info receives redacted bodies with "***"
    replacing content fields.
    """
    from src.services.gateway_service import _debug_and_respond

    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(
        return_value=json.dumps(
            {"choices": [{"message": {"content": "secret answer"}}]}
        ).encode()
    )
    upstream_response.aclose = AsyncMock()

    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.__str__ = lambda self: "http://test/v1/chat/completions"
    request.headers = {"authorization": "Bearer test-token"}

    request_body = json.dumps(
        {"messages": [{"role": "user", "content": "secret prompt"}]}
    ).encode()

    with patch("src.services.gateway_service._log_debug_info") as mock_log_debug_info:
        response = await _debug_and_respond(
            upstream_response=upstream_response,
            debug_mode="no_content",
            instance_name="test_instance",
            provider_type="openai_like",
            request=request,
            request_body=request_body,
        )

        # _log_debug_info should have been called
        assert mock_log_debug_info.called

        # The bodies passed to _log_debug_info should be sanitized
        # (redacted by redact_content), not the original raw bodies
        call_kwargs = mock_log_debug_info.call_args[1]
        logged_request_body = call_kwargs["request_body"]
        logged_response_body = call_kwargs["response_body"]

        # Verify content was redacted — "***" replaces actual content strings
        assert "***" in logged_request_body.decode()
        assert "secret prompt" not in logged_request_body.decode()
        assert "***" in logged_response_body.decode()
        assert "secret answer" not in logged_response_body.decode()


@pytest.mark.asyncio
async def test_log_debug_info_exception_does_not_block_response():
    """
    Mock _log_debug_info to raise an exception → verify response is still
    returned to client. Debug logging failures must never block the response.
    """
    from src.services.gateway_service import _debug_and_respond

    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=b"Success response body")
    upstream_response.aclose = AsyncMock()

    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.__str__ = lambda self=None: "http://test/v1/chat/completions"
    request.headers = {"authorization": "Bearer test-token"}

    request_body = b'{"model": "gpt-4"}'

    with patch(
        "src.services.gateway_service._log_debug_info",
        side_effect=RuntimeError("Logging crashed!"),
    ):
        response = await _debug_and_respond(
            upstream_response=upstream_response,
            debug_mode="no_content",
            instance_name="test_instance",
            provider_type="openai_like",
            request=request,
            request_body=request_body,
        )

    # Response must still be returned despite logging failure
    assert isinstance(response, StarletteResponse)
    assert response.status_code == 200
    assert response.body == b"Success response body"


@pytest.mark.asyncio
async def test_aread_exception_does_not_block_response():
    """
    Mock upstream_response.aread() to raise → verify client still gets a
    response (with empty body). The aread failure must not crash the handler.
    """
    from src.services.gateway_service import _debug_and_respond

    upstream_response = MagicMock()
    upstream_response.status_code = 200
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(side_effect=ConnectionError("Network failure"))
    upstream_response.aclose = AsyncMock()

    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.__str__ = lambda self=None: "http://test/v1/chat/completions"
    request.headers = {"authorization": "Bearer test-token"}

    request_body = b'{"model": "gpt-4"}'

    response = await _debug_and_respond(
        upstream_response=upstream_response,
        debug_mode="no_content",
        instance_name="test_instance",
        provider_type="openai_like",
        request=request,
        request_body=request_body,
    )

    # Response must still be returned despite aread failure
    assert isinstance(response, StarletteResponse)
    assert response.status_code == 200
    # Body should be empty (fallback when aread fails)
    assert response.body == b""
    # aclose must still have been called
    assert upstream_response.aclose.called


@pytest.mark.asyncio
async def test_end_to_end_no_content_with_openai_like():
    """
    Full end-to-end: using TestClient with mocked upstream, verify that
    no_content debug mode logs metadata + redacted content, and the client
    gets the full (un-redacted) response.
    """
    from src.services.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(
        provider_type="openai_like", keys_path="keys/test/"
    )
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
        return_value=(upstream_response, CheckResult.success(100))
    )

    # Mock HTTP client factory with proper AsyncMock
    mock_http_client = MagicMock()
    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(return_value=mock_http_client)
    mock_http_factory.close_all = AsyncMock()

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
            "src.services.gateway_service.HttpClientFactory",
            return_value=mock_http_factory,
        ),
        patch("src.services.gateway_service.GatewayCache") as MockGatewayCache,
        patch("src.services.gateway_service._get_token_from_headers") as mock_get_token,
        patch("src.services.gateway_service.get_provider", return_value=mock_provider),
        patch("src.services.gateway_service._log_debug_info") as mock_log_debug_info,
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

        # Client gets full response (not redacted)
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["choices"][0]["message"]["content"] == "Hello world"

        # _log_debug_info was called with pre-sanitized (redacted) bodies
        assert mock_log_debug_info.called
        call_kwargs = mock_log_debug_info.call_args[1]
        logged_request_body = call_kwargs["request_body"]
        logged_response_body = call_kwargs["response_body"]

        # The logged bodies should have "***" instead of actual content
        assert "***" in logged_request_body.decode()
        assert "***" in logged_response_body.decode()
        # Original content should NOT appear in logged bodies
        assert "Hello world" not in logged_response_body.decode()


def test_dead_code_removed_in_openai_like_proxy_request():
    """
    Static check: verify proxy_request in openai_like.py no longer has
    duplicated if/else branches with identical bodies (dead code removal).
    """
    import src.providers.impl.openai_like as oai_mod

    source = inspect.getsource(oai_mod.OpenAILikeProvider.proxy_request)

    # The proxy_request should be a thin wrapper with no duplicated branches.
    # We check that there are no if/else blocks where both branches are identical.
    # A simple heuristic: the source should not contain two consecutive
    # return statements inside an if/else that look the same.
    # More practically: the source should be short (thin wrapper).
    lines = source.strip().split("\n")
    # proxy_request is now ~44 lines (thin wrapper). If it were still
    # containing duplicated branches, it would be much longer.
    assert len(lines) < 50, (
        f"proxy_request has {len(lines)} lines — expected a thin wrapper < 50 lines. "
        f"Possible duplicated if/else branches still present."
    )

    # Also verify no "if" followed by "else" with identical return values
    # (simple pattern check for duplicated branches)
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
    from src.services.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(
        provider_type="openai_like", keys_path="keys/test/"
    )
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="no_content",
        retry=RetryPolicyConfig(enabled=True),
    )
    accessor.get_enabled_providers.return_value = {"my_provider": provider_config}
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

        with caplog.at_level(logging.WARNING, logger="src.services.gateway_service"):
            app = create_app(accessor)
            # The lifespan startup runs when TestClient enters the context
            with TestClient(app):
                pass  # Just trigger startup; no request needed

    # Check that a WARNING was logged mentioning the provider name and debug mode
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
    from src.services.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(
        provider_type="openai_like", keys_path="keys/test/"
    )
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

        with caplog.at_level(logging.WARNING, logger="src.services.gateway_service"):
            app = create_app(accessor)
            # Trigger lifespan startup via TestClient
            with TestClient(app):
                pass

    # No WARNING about retry being ignored should appear
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
    from src.services.gateway_service import create_app

    accessor = MagicMock()
    provider_config = ProviderConfig(
        provider_type="openai_like", keys_path="keys/test/"
    )
    provider_config.enabled = True
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy = GatewayPolicyConfig(
        debug_mode="disabled",
        retry=RetryPolicyConfig(enabled=True),
    )
    accessor.get_enabled_providers.return_value = {"my_provider": provider_config}
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

        with caplog.at_level(logging.WARNING, logger="src.services.gateway_service"):
            app = create_app(accessor)
            # Trigger lifespan startup via TestClient
            with TestClient(app):
                pass

    # No WARNING about debug mode should appear
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
    Config with debug_mode: "headers_only" → Pydantic validation error
    at startup. The Literal type only accepts "disabled", "no_content",
    "full_body".
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(debug_mode="headers_only")

    # Verify the error mentions debug_mode
    errors = exc_info.value.errors()
    assert any(
        e["loc"] == ("debug_mode",) for e in errors
    ), f"Expected validation error on 'debug_mode' field, got: {errors}"
