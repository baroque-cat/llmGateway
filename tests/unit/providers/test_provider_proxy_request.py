from unittest.mock import AsyncMock

import httpx
import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.providers.base import AIBaseProvider


# --- Realistic Mock Provider ---
class RealisticMockProvider(AIBaseProvider):
    """
    Simulates a real provider (like OpenAILike) to test the Base class pipeline.
    """

    async def _parse_proxy_error(self, response, content=None):
        # Simulate standard mapping logic found in real providers
        status = response.status_code

        # Logic: If content is None, we MUST rely on status code (Zero-Overhead)
        # If content is present, we might refine it (simulated here)

        msg = "Body NOT read"
        if content:
            msg = "Body READ"

        if status == 400:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg, status_code=status)
        if status == 401:
            return CheckResult.fail(ErrorReason.INVALID_KEY, msg, status_code=status)
        if status == 500:
            return CheckResult.fail(ErrorReason.SERVER_ERROR, msg, status_code=status)

        return CheckResult.fail(ErrorReason.UNKNOWN, msg, status_code=status)

    # Stubs for abstract methods
    async def parse_request_details(self, path, content):
        pass

    def _get_headers(self, token):
        return {}

    async def check(self, client, token, **kwargs):
        pass

    async def inspect(self, client, token, **kwargs):
        pass

    async def proxy_request(
        self, client, token, method, headers, path, query_params, content
    ):
        pass


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
    # If read is called, return dummy JSON
    response.aread = AsyncMock(
        return_value=b'{"error": {"type": "context_length_exceeded"}}'
    )
    return response


# --- 1. DEFAULT BEHAVIOR TESTS ---


@pytest.mark.asyncio
async def test_default_400_behavior(mock_client, mock_response):
    """
    Scenario: Default config, Status 400.
    Expectation:
    - Body NOT read (Zero Overhead).
    - Reason is BAD_REQUEST (No penalty).
    """
    config = ProviderConfig(provider_type="openai_like")
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 400
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions
    assert result.error_reason == ErrorReason.BAD_REQUEST
    assert result.message == "Body NOT read"
    mock_response.aread.assert_not_called()  # Critical
    # For 400, stream is intentionally NOT closed (special exception in base)
    mock_response.aclose.assert_not_called()


@pytest.mark.asyncio
async def test_default_401_behavior(mock_client, mock_response):
    """
    Scenario: Default config, Status 401.
    Expectation:
    - Body NOT read (Zero Overhead).
    - Reason is INVALID_KEY (Penalty applies downstream).
    """
    config = ProviderConfig(provider_type="openai_like")
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 401
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions
    assert result.error_reason == ErrorReason.INVALID_KEY
    assert result.message == "Body NOT read"
    mock_response.aread.assert_not_called()
    # Stream is never closed by _send_proxy_request (caller owns lifecycle)
    mock_response.aclose.assert_not_called()


# --- 2. FAST FALLBACK (DEFAULT BEHAVIOR) TESTS ---


@pytest.mark.asyncio
async def test_fast_fallback_400(mock_client, mock_response):
    """
    Scenario: Default config (no debug, no error_parsing), Status 400.
    Expectation:
    - Body NOT read (Fast Fallback).
    - Reason is BAD_REQUEST (Default status mapping).
    - Stream NOT closed (special exception for 400).
    """
    config = ProviderConfig(
        provider_type="openai_like",
        gateway_policy=GatewayPolicyConfig(),
    )
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 400
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions - fast_status_mapping removed, falls through to default
    assert result.error_reason == ErrorReason.BAD_REQUEST  # Default mapping
    assert result.message == "Body NOT read"
    mock_response.aread.assert_not_called()
    # For 400, stream is intentionally NOT closed (special exception in base)
    mock_response.aclose.assert_not_called()


# --- 3. TARGETED ERROR PARSING TESTS ---


@pytest.mark.asyncio
async def test_error_parsing_triggered(mock_client, mock_response):
    """
    Scenario: Parsing enabled for 400. Status is 400.
    Expectation:
    - Body IS read (to look for details).
    """
    config = ProviderConfig(
        provider_type="openai_like",
        error_parsing=ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="e",
                    match_pattern="p",
                    map_to="invalid_key",
                )
            ],
        ),
    )
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 400
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions
    assert result.message == "Body READ"
    mock_response.aread.assert_called_once()


@pytest.mark.asyncio
async def test_error_parsing_ignored_on_mismatch(mock_client, mock_response):
    """
    Scenario: Parsing enabled for 400. Status is 500.
    Expectation:
    - Body NOT read (Optimization).
    - Returns SERVER_ERROR based on status.
    """
    config = ProviderConfig(
        provider_type="openai_like",
        error_parsing=ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="e",
                    match_pattern="p",
                    map_to="invalid_key",
                )
            ],
        ),
    )
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 500  # Mismatch
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions
    assert result.error_reason == ErrorReason.SERVER_ERROR
    assert result.message == "Body NOT read"
    mock_response.aread.assert_not_called()


# --- 4. DEBUG MODE TESTS ---


@pytest.mark.asyncio
async def test_debug_mode_force_read(mock_client, mock_response):
    """
    Scenario: Debug mode is 'full_body'.
    Expectation: Body IS read regardless of status.
    """
    config = ProviderConfig(
        provider_type="openai_like",
        gateway_policy=GatewayPolicyConfig(debug_mode="full_body"),
    )
    provider = RealisticMockProvider("test", config)

    mock_response.status_code = 500
    mock_client.send.return_value = mock_response
    request = httpx.Request("POST", "http://test")

    _, result, _body = await provider._send_proxy_request(mock_client, request)

    # Assertions
    assert result.message == "Body READ"
    mock_response.aread.assert_called_once()
