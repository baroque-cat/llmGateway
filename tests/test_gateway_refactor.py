import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.config.schemas import ProviderConfig, RetryOnErrorConfig
from fastapi import Request
from starlette.responses import StreamingResponse

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
    provider_config = ProviderConfig()
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(attempts=2, backoff_sec=0.1)
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(attempts=2, backoff_sec=0.1)
    
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    
    # Setup Cache: Return key1, then key2
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"), # First key (fails server retries)
        (1, "key1"), # Retry 1 with same key
        (2, "key2"), # Second key (success)
    ]
    
    # Sequence of results:
    # 1. Key 1: 500 (Attempt 1)
    # 2. Key 1: 500 (Attempt 2 - Exhausted)
    # 3. Key 2: 200 (Success)
    
    response_500 = MagicMock()
    response_500.status_code = 500
    
    response_200 = MagicMock()
    response_200.status_code = 200
    response_200.headers = {}
    response_200.aread = AsyncMock(return_value=b"Success")
    
    provider.proxy_request = AsyncMock(side_effect=[
        (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 1")),
        (response_500, CheckResult.fail(ErrorReason.SERVER_ERROR, "Error 2")),
        (response_200, CheckResult.success(100)),
    ])
    
    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(req, provider, instance_name)
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
    provider_config = ProviderConfig()
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(attempts=0)
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=3, backoff_sec=10.0, backoff_factor=2.0
    )
    
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"), (2, "key2"), (3, "key3")
    ]
    
    # All keys fail with INVALID_KEY
    resp_401 = MagicMock()
    resp_401.status_code = 401
    provider.proxy_request = AsyncMock(return_value=(resp_401, CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid")))
    
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
    provider_config = ProviderConfig()
    provider_config.models = {"gpt-4": {}}
    provider_config.gateway_policy.retry.enabled = True
    provider_config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(attempts=2, backoff_sec=0.1)
    
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"), (2, "key2")
    ]
    
    # 1. First response is 400 mapped to INVALID_KEY (Fatal)
    resp_400 = MagicMock()
    resp_400.status_code = 400
    
    # 2. Second response is 200
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.aread = AsyncMock(return_value=b"Success")
    
    # We simulate the provider doing the mapping internally or via error parsing
    # Here we just return the result that implies the mapping happened
    provider.proxy_request = AsyncMock(side_effect=[
        (resp_400, CheckResult.fail(ErrorReason.INVALID_KEY, "Mapped from 400")),
        (resp_200, CheckResult.success(100)),
    ])
    
    with patch("asyncio.sleep", side_effect=mock_sleep):
        response = await _handle_buffered_retryable_request(req, provider, instance_name)
        # Give extra time for background tasks
        await asyncio.sleep(0.01)
    
    assert response.status_code == 200
    # Key 1 should be penalized because INVALID_KEY is fatal
    assert req.app.state.db_manager.keys.update_status.call_count >= 1
    # Should have tried 2 keys
    assert req.app.state.gateway_cache.get_key_from_pool.call_count == 2
