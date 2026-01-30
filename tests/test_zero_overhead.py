
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.config.schemas import ProviderConfig, GatewayPolicyConfig, ErrorParsingConfig, ErrorParsingRule
from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.providers.base import AIBaseProvider
import httpx

# Mock concrete implementation
class MockProvider(AIBaseProvider):
    async def _parse_proxy_error(self, response, content=None):
        # Simply return success so we can check if content was passed
        reason = ErrorReason.UNKNOWN
        msg = "Content was None"
        if content:
             msg = "Content was Read"
        
        return CheckResult.fail(reason, msg, status_code=response.status_code)
    
    # Stubs
    async def parse_request_details(self, path, content): pass
    def _get_headers(self, token): return {}
    async def check(self, client, token, **kwargs): pass
    async def inspect(self, client, token, **kwargs): pass
    async def proxy_request(self, client, token, method, headers, path, query_params, content): pass

@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.send = AsyncMock()
    return client

@pytest.fixture
def mock_response():
    response = AsyncMock(spec=httpx.Response)
    response.status_code = 400
    response.is_success = False
    response.headers = {}
    response.aclose = AsyncMock()
    response.aread = AsyncMock(return_value=b'{"error": "parsed_error"}')
    return response

@pytest.mark.asyncio
async def test_unsafe_mapping_fast_fail(mock_client, mock_response):
    """
    Scenario: Unsafe mapping is configured for 400.
    Expectation: Fast fail (aclose called), body NOT read.
    """
    config = ProviderConfig(
        provider_type="mock",
        gateway_policy=GatewayPolicyConfig(
            unsafe_status_mapping={400: "invalid_key"}
        )
    )
    provider = MockProvider("test", config)
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    resp, result = await provider._send_proxy_request(mock_client, request)

    assert result.error_reason == ErrorReason.INVALID_KEY
    assert "Fast fail" in result.message
    mock_response.aread.assert_not_called()
    mock_response.aclose.assert_called_once()

@pytest.mark.asyncio
async def test_debug_mode_reads_body(mock_client, mock_response):
    """
    Scenario: Debug mode is 'full_body'.
    Expectation: Body IS read.
    """
    config = ProviderConfig(
        provider_type="mock",
        gateway_policy=GatewayPolicyConfig(
            debug_mode="full_body"
        )
    )
    provider = MockProvider("test", config)
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    resp, result = await provider._send_proxy_request(mock_client, request)

    mock_response.aread.assert_called_once()
    assert result.message == "Content was Read"

@pytest.mark.asyncio
async def test_error_parsing_triggered_reads_body(mock_client, mock_response):
    """
    Scenario: Error parsing enabled AND rule exists for status code.
    Expectation: Body IS read.
    """
    config = ProviderConfig(
        provider_type="mock",
        gateway_policy=GatewayPolicyConfig(
            error_parsing=ErrorParsingConfig(
                enabled=True,
                rules=[ErrorParsingRule(status_code=400, error_path="e", match_pattern="p", map_to="x")]
            )
        )
    )
    provider = MockProvider("test", config)
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    resp, result = await provider._send_proxy_request(mock_client, request)

    mock_response.aread.assert_called_once()
    assert result.message == "Content was Read"

@pytest.mark.asyncio
async def test_error_parsing_ignored_does_not_read_body(mock_client, mock_response):
    """
    Scenario: Error parsing enabled BUT NO rule for this status code (e.g., 500 vs 400).
    Expectation: Body NOT read (Fast Fallback).
    """
    mock_response.status_code = 500 # Rule is for 400
    
    config = ProviderConfig(
        provider_type="mock",
        gateway_policy=GatewayPolicyConfig(
            error_parsing=ErrorParsingConfig(
                enabled=True,
                rules=[ErrorParsingRule(status_code=400, error_path="e", match_pattern="p", map_to="x")]
            )
        )
    )
    provider = MockProvider("test", config)
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    resp, result = await provider._send_proxy_request(mock_client, request)

    mock_response.aread.assert_not_called()
    mock_response.aclose.assert_called_once()
    assert result.message == "Content was None"

@pytest.mark.asyncio
async def test_default_behavior_fast_fallback(mock_client, mock_response):
    """
    Scenario: No config.
    Expectation: Body NOT read (Fast Fallback).
    """
    config = ProviderConfig(provider_type="mock")
    provider = MockProvider("test", config)
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    resp, result = await provider._send_proxy_request(mock_client, request)

    mock_response.aread.assert_not_called()
    mock_response.aclose.assert_called_once()
    assert result.message == "Content was None"
