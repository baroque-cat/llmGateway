#!/usr/bin/env python3
"""
Integration test for retry synergy between server errors and key errors.
Validates that server_error_attempts resets when key rotates, that
limits are respected, and that original upstream responses are forwarded
transparently (not synthetic 503 JSON errors).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import ProviderConfig, RetryOnErrorConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult


@pytest.mark.asyncio
async def test_server_error_then_key_error_synergy_original_error_forwarded():
    """
    Scenario: 2 keys in pool, server_error limit=2, key_error limit=2.
    Attempt 1 (key1): Server error (Timeout) → server_error_attempts=1, discard_response.
    Attempt 2 (key1): Fatal error (INVALID_KEY) → key rotation, server_error_attempts=0,
        key_error_attempts=1, discard_response.
    Attempt 3 (key2): Server error → server_error_attempts=1, discard_response.
    Attempt 4 (key2): Server error → server_error_attempts=2 (exhausted), key rotation,
        key_error_attempts=2 (exhausted), forward_error_to_client.

    After exhausting all attempts, client gets original upstream response (status 500),
    NOT a synthetic 503 JSON error.  Counters and key rotation unchanged.
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Explicitly set AsyncMock for the method
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: server attempts = 2, key attempts = 2
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

    # Setup Cache: two keys, first key will be used twice, then second key twice
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # Attempt 1
        (1, "key1"),  # Attempt 2 (same key, server error didn't rotate)
        (2, "key2"),  # Attempt 3 (after key rotation)
        (2, "key2"),  # Attempt 4 (same key, server error again)
    ]

    # Sequence of responses and check results — mock upstream responses
    # with aread support so forward_error_to_client can read the body
    response_timeout = MagicMock()
    response_timeout.status_code = 504
    response_timeout.headers = {}
    response_timeout.aclose = AsyncMock()
    response_timeout.aread = AsyncMock(return_value=b'{"error": "timeout"}')

    response_invalid_key = MagicMock()
    response_invalid_key.status_code = 401
    response_invalid_key.headers = {}
    response_invalid_key.aclose = AsyncMock()
    response_invalid_key.aread = AsyncMock(return_value=b'{"error": "invalid key"}')

    response_server_error = MagicMock()
    response_server_error.status_code = 500
    response_server_error.headers = {}
    response_server_error.aclose = AsyncMock()
    response_server_error.aread = AsyncMock(
        return_value=b'{"error": "Internal server error"}'
    )

    # proxy_request now returns 3-tuples: (response, check_result, body_bytes)
    # body_bytes=None means the stream is still open (zero-overhead path)
    provider.proxy_request = AsyncMock(
        side_effect=[
            # Attempt 1: Timeout (server error) on key1
            (response_timeout, CheckResult.fail(ErrorReason.TIMEOUT, "Timeout"), None),
            # Attempt 2: INVALID_KEY (fatal) on key1 → rotation
            (
                response_invalid_key,
                CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key"),
                None,
            ),
            # Attempt 3: Server error on key2
            (
                response_server_error,
                CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error"),
                None,
            ),
            # Attempt 4: Server error on key2 (exhaustion)
            (
                response_server_error,
                CheckResult.fail(ErrorReason.SERVER_ERROR, "Server error"),
                None,
            ),
        ]
    )

    # Capture original sleep to allow yielding control
    original_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await original_sleep(0)  # yield control without waiting

    discard_mock = AsyncMock()

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch("src.services.gateway.gateway_service.discard_response", discard_mock),
    ):
        # After exhausting all attempts, the client receives the original upstream
        # response transparently — NOT a synthetic 503 JSON error.
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # Give background tasks (like _report_key_failure) a chance to run
        await asyncio.sleep(0.01)

    # --- Assertions ---
    # 1. Exactly 4 proxy_request calls
    assert provider.proxy_request.call_count == 4
    # 2. Exactly 4 get_key_from_pool calls (verify side_effect consumed)
    assert req.app.state.gateway_cache.get_key_from_pool.call_count == 4
    # 3. Key 1 removed from pool after fatal error
    req.app.state.gateway_cache.remove_key_from_pool.assert_any_call(
        instance_name, "gpt-4", 1
    )
    # 4. Key 2 removed from pool after server error exhaustion
    req.app.state.gateway_cache.remove_key_from_pool.assert_any_call(
        instance_name, "gpt-4", 2
    )
    # 5. DB updated for both keys (each key failure triggers update_status)
    assert req.app.state.db_manager.keys.update_status.call_count == 2
    # 6. discard_response called for 3 intermediate attempts (not inline aclose)
    assert discard_mock.call_count == 3
    # 7. Final response has ORIGINAL upstream status code (500), NOT synthetic 503
    assert response.status_code == 500
    # 8. Final response body is the ORIGINAL upstream body, NOT synthetic JSON
    assert response.body == b'{"error": "Internal server error"}'


@pytest.mark.asyncio
async def test_counter_reset_on_key_rotation_unchanged():
    """
    Verify that server_error_attempts resets to 0 on key rotation — behavior unchanged,
    but discard_response() is used instead of inline aclose() for intermediate attempts.

    Scenario: 2 keys, server_error limit=2, key_error limit=2.
    Attempt 1 (key1): TIMEOUT → server_error_attempts=1, discard_response.
    Attempt 2 (key1): INVALID_KEY → key rotation, server_error_attempts=0,
        key_error_attempts=1, discard_response.
    Attempt 3 (key2): TIMEOUT → server_error_attempts=1, discard_response.
        (Proves counter was reset: if not reset, this would be attempt 3 and would
         exhaust the server_error limit, causing premature key rotation.)
    Attempt 4 (key2): INVALID_KEY → key rotation, server_error_attempts=0,
        key_error_attempts=2 (exhausted), forward_error_to_client.

    The counter-reset-on-rotation behavior is unchanged from before the
    transparent-error-forwarding change.  The only difference is that
    discard_response() is used for intermediate attempts instead of inline aclose().
    """
    from src.services.gateway.gateway_service import _handle_buffered_retryable_request

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Setup Config: server attempts = 2, key attempts = 2
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

    # Setup Cache: key1 twice, then key2 twice
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),  # Attempt 1
        (1, "key1"),  # Attempt 2 (same key, server error didn't rotate)
        (2, "key2"),  # Attempt 3 (after key rotation)
        (2, "key2"),  # Attempt 4 (same key, server error didn't rotate)
    ]

    # Mock upstream responses — separate objects per attempt for clarity
    response_timeout_k1 = MagicMock()
    response_timeout_k1.status_code = 504
    response_timeout_k1.headers = {}
    response_timeout_k1.aclose = AsyncMock()
    response_timeout_k1.aread = AsyncMock(return_value=b'{"error": "timeout on key1"}')

    response_invalid_key_k1 = MagicMock()
    response_invalid_key_k1.status_code = 401
    response_invalid_key_k1.headers = {}
    response_invalid_key_k1.aclose = AsyncMock()
    response_invalid_key_k1.aread = AsyncMock(return_value=b'{"error": "invalid key1"}')

    response_timeout_k2 = MagicMock()
    response_timeout_k2.status_code = 504
    response_timeout_k2.headers = {}
    response_timeout_k2.aclose = AsyncMock()
    response_timeout_k2.aread = AsyncMock(return_value=b'{"error": "timeout on key2"}')

    response_invalid_key_k2 = MagicMock()
    response_invalid_key_k2.status_code = 401
    response_invalid_key_k2.headers = {}
    response_invalid_key_k2.aclose = AsyncMock()
    response_invalid_key_k2.aread = AsyncMock(return_value=b'{"error": "invalid key2"}')

    # proxy_request returns 3-tuples: (response, check_result, body_bytes)
    provider.proxy_request = AsyncMock(
        side_effect=[
            # Attempt 1: Server error (Timeout) on key1
            (
                response_timeout_k1,
                CheckResult.fail(ErrorReason.TIMEOUT, "Timeout"),
                None,
            ),
            # Attempt 2: Key error (INVALID_KEY) on key1 → rotation
            (
                response_invalid_key_k1,
                CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key"),
                None,
            ),
            # Attempt 3: Server error (Timeout) on key2
            (
                response_timeout_k2,
                CheckResult.fail(ErrorReason.TIMEOUT, "Timeout"),
                None,
            ),
            # Attempt 4: Key error (INVALID_KEY) on key2 → rotation, exhausted
            (
                response_invalid_key_k2,
                CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key"),
                None,
            ),
        ]
    )

    original_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await original_sleep(0)

    discard_mock = AsyncMock()

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch("src.services.gateway.gateway_service.discard_response", discard_mock),
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        await asyncio.sleep(0.01)

    # --- Assertions ---
    # 1. Exactly 4 proxy_request calls (proves counter reset: attempt 3 on key2
    #    is a fresh server_error attempt, not a continuation from key1)
    assert provider.proxy_request.call_count == 4
    # 2. Exactly 4 get_key_from_pool calls (key1, key1, key2, key2)
    assert req.app.state.gateway_cache.get_key_from_pool.call_count == 4
    # 3. Both keys removed from pool after key errors
    req.app.state.gateway_cache.remove_key_from_pool.assert_any_call(
        instance_name, "gpt-4", 1
    )
    req.app.state.gateway_cache.remove_key_from_pool.assert_any_call(
        instance_name, "gpt-4", 2
    )
    # 4. DB updated for both keys
    assert req.app.state.db_manager.keys.update_status.call_count == 2
    # 5. discard_response called for 3 intermediate attempts (attempts 1, 2, 3)
    #    NOT inline aclose() — verifies the discard() usage change
    assert discard_mock.call_count == 3
    # 6. Final response is original upstream 401 (NOT synthetic 503)
    assert response.status_code == 401
    # 7. Final response body is original upstream body (NOT synthetic JSON)
    assert response.body == b'{"error": "invalid key2"}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
