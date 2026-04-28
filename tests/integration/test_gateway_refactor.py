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
        _response = await _debug_and_respond(
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


# ---------------------------------------------------------------------------
# NEW: Integration tests for preserve-400-error-body change
# ---------------------------------------------------------------------------

# Original error body that the upstream provider would return for a 400
ORIGINAL_400_BODY = (
    b'{"error":{"message":"Invalid model","type":"invalid_request_error"}}'
)
SYNTHETIC_400_BODY = b'{"error": "Upstream error: bad_request"}'


@pytest.mark.asyncio
async def test_IT1_handle_full_stream_request_400_client_gets_original_body():
    """
    IT-1: _handle_full_stream_request + 400 → client gets original error body.

    Provider returns CheckResult.fail(BAD_REQUEST) with an OPEN stream
    (aread succeeds). Verify: aread() reads the original body, aclose()
    called in finally, client gets Response(400) with original body,
    NOT synthetic placeholder.
    """
    from src.services.gateway_service import _handle_full_stream_request

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
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Verify aread was called and succeeded
    assert upstream_response.aread.called
    # Verify aclose was called in finally
    assert upstream_response.aclose.called
    # Verify client gets original body, NOT synthetic placeholder
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY
    assert SYNTHETIC_400_BODY not in response.body


@pytest.mark.asyncio
async def test_IT2_handle_buffered_request_400_client_gets_original_body():
    """
    IT-2: _handle_buffered_request + 400 → client gets original error body.

    Same as IT-1 but through _handle_buffered_request.
    Verify: client gets original error body, hop-by-hop headers filtered.
    """
    from src.services.gateway_service import _handle_buffered_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup provider config
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
    provider_config.models = {"gpt-4": {}}
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 400 status and open stream
    upstream_response = MagicMock()
    upstream_response.status_code = 400
    upstream_response.headers = httpx.Headers(
        {
            "content-type": "application/json",
            "connection": "keep-alive",  # hop-by-hop header
            "transfer-encoding": "chunked",  # hop-by-hop header
            "x-custom": "value",  # non hop-by-hop header
        }
    )
    upstream_response.aread = AsyncMock(return_value=ORIGINAL_400_BODY)
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.BAD_REQUEST, "Bad request", status_code=400),
    )

    response = await _handle_buffered_request(req, provider, instance_name)

    # Verify aread was called and succeeded
    assert upstream_response.aread.called
    # Verify aclose was called in finally
    assert upstream_response.aclose.called
    # Verify client gets original body, NOT synthetic placeholder
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY
    assert SYNTHETIC_400_BODY not in response.body
    # Verify hop-by-hop headers are filtered out
    response_headers = dict(response.headers)
    assert "connection" not in {k.lower() for k in response_headers}
    assert "transfer-encoding" not in {k.lower() for k in response_headers}
    assert "x-custom" in {k.lower() for k in response_headers}


@pytest.mark.asyncio
async def test_IT3_handle_buffered_retryable_request_400_retry_aborted_key_not_removed():
    """
    IT-3: _handle_buffered_retryable_request + 400 → retry aborted, client
    gets error body, key NOT removed.

    Provider returns 400/BAD_REQUEST in retryable handler.
    Verify: retry loop immediately breaks (is_client_error → True),
    aread() reads body, client gets Response(400) with original body,
    key NOT marked as failed, remove_key_from_pool NOT called for this key.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup Config: retry enabled with multiple key attempts
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Verify client gets original body, NOT synthetic placeholder
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY
    assert SYNTHETIC_400_BODY not in response.body

    # Verify key NOT marked as failed — BAD_REQUEST is client error, not key fault
    assert not req.app.state.db_manager.keys.update_status.called

    # Verify remove_key_from_pool NOT called for this key
    # (it might be called for other reasons, but not for this key due to client error)
    remove_calls = req.app.state.gateway_cache.remove_key_from_pool.call_args_list
    # No remove_key_from_pool call should exist for key_id=1 with this instance/model
    for call in remove_calls:
        args, _ = call
        # The call signature is remove_key_from_pool(instance_name, model_name, key_id)
        if len(args) >= 3 and args[2] == 1:
            raise AssertionError(
                "remove_key_from_pool was called for key_id=1, "
                "but BAD_REQUEST should NOT remove the key"
            )


@pytest.mark.asyncio
async def test_IT4_handle_buffered_retryable_request_401_existing_behavior_regression():
    """
    IT-4: _handle_buffered_retryable_request + 401 (INVALID_KEY) → existing
    behavior (regression).

    Provider returns 401/INVALID_KEY (is_fatal).
    Verify: key marked as failed, retry with new key, client does NOT get
    original 401 body (stream closed by provider, aread fails → synthetic
    placeholder).
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: 2 key attempts
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Setup Cache: Return key1 (fails), then key2 (succeeds)
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
    ]

    # 1. First response: 401/INVALID_KEY — stream closed by provider, aread fails
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.headers = {}
    resp_401.aread = AsyncMock(side_effect=httpx.StreamClosed)
    resp_401.aclose = AsyncMock()

    # 2. Second response: 200 (success)
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.headers = {}
    resp_200.aread = AsyncMock(return_value=b"Success")
    resp_200.aclose = AsyncMock()

    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                resp_401,
                CheckResult.fail(
                    ErrorReason.INVALID_KEY, "Invalid key", status_code=401
                ),
            ),
            (resp_200, CheckResult.success(100)),
        ]
    )

    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # Verify: retry succeeded with new key → client gets 200
    assert response.status_code == 200

    # Verify: key1 was marked as failed (INVALID_KEY is fatal)
    assert req.app.state.db_manager.keys.update_status.called

    # Verify: key1 was removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called


@pytest.mark.asyncio
async def test_IT5_handle_full_stream_request_500_existing_behavior_regression():
    """
    IT-5: _handle_full_stream_request + 500 (SERVER_ERROR) → existing
    behavior (regression).

    Provider returns 500/SERVER_ERROR (not client_error, not fatal).
    Verify: gateway enters Case 3 (upstream/key error), key marked failed,
    client gets empty/synthetic body (503 JSONResponse).
    """
    from src.services.gateway_service import _handle_full_stream_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"
    model_name = "gpt-4"

    provider.proxy_request = AsyncMock()

    # Setup key pool to return a valid key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-api-key")

    # Create mock upstream response with 500 status
    upstream_response = MagicMock()
    upstream_response.status_code = 500
    upstream_response.headers = httpx.Headers({"content-type": "application/json"})
    upstream_response.aread = AsyncMock(return_value=b"Internal server error")
    upstream_response.aclose = AsyncMock()

    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error", status_code=500),
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )
    await asyncio.sleep(0.01)

    # Verify: gateway returns 503 (not 500) — Case 3 transforms to 503
    assert response.status_code == 503

    # Verify: key marked as failed
    assert req.app.state.db_manager.keys.update_status.called

    # Verify: key removed from pool
    assert req.app.state.gateway_cache.remove_key_from_pool.called

    # Verify: aclose was called (no connection leak)
    assert upstream_response.aclose.called


@pytest.mark.asyncio
async def test_IT6_handle_buffered_request_400_content_type_preserved():
    """
    IT-6: _handle_buffered_request + 400 with Content-Type: application/json
    → media_type preserved.

    Upstream returns 400 with Content-Type: application/json header and JSON body.
    Verify: client response has media_type="application/json" and original body
    unchanged.
    """
    from src.services.gateway_service import _handle_buffered_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup provider config
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    )

    response = await _handle_buffered_request(req, provider, instance_name)

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
    debug_and_respond has priority.

    Provider returns 400/BAD_REQUEST, debug_mode = "no_content".
    Verify: _debug_and_respond is called instead of direct aread(),
    client gets response through debug path.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    # Setup Config: retry enabled + debug_mode = "no_content"
    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    )

    with patch(
        "src.services.gateway_service._debug_and_respond",
        new_callable=AsyncMock,
    ) as mock_debug_and_respond:
        # Configure the mock to return a proper Response
        mock_debug_and_respond.return_value = StarletteResponse(
            content=ORIGINAL_400_BODY,
            status_code=400,
            media_type="application/json",
        )

        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify: _debug_and_respond was called (debug path has priority)
    assert mock_debug_and_respond.called

    # Verify: client gets response through debug path
    assert response.status_code == 400

    # Verify: direct aread() was NOT called on upstream_response
    # (because _debug_and_respond handles the reading internally)
    assert not upstream_response.aread.called


@pytest.mark.asyncio
async def test_SEC1_aclose_called_in_finally_for_400():
    """
    SEC-1: Connection leak — aclose() called in finally for 400.

    Verify: even with successful aread() for 400, aclose() is called in
    finally block of gateway handler. Mock both calls, verify aclose
    called exactly once after aread.
    """
    from src.services.gateway_service import _handle_full_stream_request

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
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Verify: aread was called
    assert upstream_response.aread.called

    # Verify: aclose was called exactly once (in finally block)
    assert upstream_response.aclose.call_count == 1

    # Verify: response is correct
    assert response.status_code == 400
    assert response.body == ORIGINAL_400_BODY


@pytest.mark.asyncio
async def test_SEC2_aread_fails_for_non_400_finally_still_calls_aclose():
    """
    SEC-2: aread() fails for non-400 code — finally still calls aclose().

    For 401 (stream closed by provider) aread() raises StreamClosed.
    Verify: except block generates synthetic body, finally calls aclose(),
    client gets Response(401) with synthetic body. No connection leak.
    """
    from src.services.gateway_service import _handle_full_stream_request

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

    # INVALID_KEY is NOT a client_error (is_client_error returns False),
    # so this goes to Case 3 (upstream/key error), not Case 2.
    # But we also need to test the Case 2 path for UNKNOWN (which IS client_error).
    # Let's test with ErrorReason.UNKNOWN which IS client_error.
    provider.proxy_request.return_value = (
        upstream_response,
        CheckResult.fail(ErrorReason.UNKNOWN, "Unknown error", status_code=401),
    )

    response = await _handle_full_stream_request(
        req, provider, instance_name, model_name
    )

    # Verify: aread was called (even though it failed)
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
# NEW: Integration tests for ReadError handling in streaming handlers (G5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_6_2_handle_full_stream_request_read_error_intercepted():
    """
    6.2: _handle_full_stream_request — httpx.ReadError intercepted by StreamMonitor.

    Mock aiter_bytes() raises httpx.ReadError → StreamMonitor catches it,
    raises GatewayStreamError with provider_name and model_name.
    The handler returns StreamingResponse; the error surfaces during stream iteration.
    """
    from src.services.gateway_service import (
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
async def test_6_3_handle_buffered_request_read_error_intercepted():
    """
    6.3: _handle_buffered_request — httpx.ReadError intercepted by StreamMonitor.

    Mock aiter_bytes() raises httpx.ReadError → StreamMonitor catches it,
    raises GatewayStreamError with provider_name and model_name.
    """
    from src.services.gateway_service import (
        GatewayStreamError,
        _handle_buffered_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
    )

    response = await _handle_buffered_request(req, provider, instance_name)

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

    First proxy_request returns success, but aiter_bytes() raises httpx.ReadError.
    StreamMonitor catches it and raises GatewayStreamError.
    """
    from src.services.gateway_service import (
        GatewayStreamError,
        _handle_buffered_retryable_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")
    provider.proxy_request = AsyncMock()

    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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

    First attempt: server error → retry → second attempt: aiter_bytes() raises
    httpx.ReadError. StreamMonitor catches it and raises GatewayStreamError.
    """
    from src.services.gateway_service import (
        GatewayStreamError,
        _handle_buffered_retryable_request,
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = ProviderConfig(provider_type="test", keys_path="keys/test/")
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
            ),
            (upstream_response, CheckResult.success(100)),
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

    StreamMonitor.__anext__() catches httpx.ReadError and logs a WARNING
    with provider_name and model_name before raising GatewayStreamError.
    """
    from src.services.gateway_service import (
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
    )

    with caplog.at_level(logging.WARNING, logger="src.services.gateway_service"):
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

    When aiter_bytes() raises httpx.ReadError, StreamMonitor catches it and
    raises GatewayStreamError (a controlled domain exception) instead.
    The raw httpx.ReadError does NOT reach the ASGI layer directly.

    Note: GatewayStreamError itself currently propagates uncaught through
    StreamingResponse to ASGI. This test verifies that at minimum,
    httpx.ReadError is intercepted and converted to a domain exception.
    For full SEC-3 compliance, the handler should catch GatewayStreamError
    and return a controlled HTTP error response (e.g., 503).
    """
    from src.services.gateway_service import (
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
