"""
Unit tests for verifying the type correctness of gateway_service helper functions
with httpx.Response (not Starlette.Response).
"""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.responses import StreamingResponse

from src.services.gateway_service import (
    _create_proxied_streaming_response,
    _generate_streaming_body,
)


@pytest.mark.asyncio
async def test_generate_streaming_body_with_httpx_response():
    """
    Verify that _generate_streaming_body accepts an httpx.Response and
    streams its body correctly.
    """
    # Create a mock httpx.Response
    mock_response = AsyncMock(spec=httpx.Response)

    # Create an async iterator that yields three chunks
    async def chunk_iterator():
        for chunk in [b"chunk1", b"chunk2", b"chunk3"]:
            yield chunk

    # Mock aiter_bytes to return the async iterator
    mock_response.aiter_bytes.return_value = chunk_iterator()
    mock_response.aclose = AsyncMock()

    # Collect the chunks produced by the generator
    chunks = []
    async for chunk in _generate_streaming_body(mock_response):
        chunks.append(chunk)

    # Verify the chunks match
    assert chunks == [b"chunk1", b"chunk2", b"chunk3"]
    # Ensure aclose was called (finally block)
    mock_response.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_create_proxied_streaming_response_with_httpx_response():
    """
    Verify that _create_proxied_streaming_response accepts an httpx.Response
    and returns a properly configured StreamingResponse.
    """
    # Create a mock httpx.Response
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "content-length": "123",
        "connection": "keep-alive",
        "x-custom-header": "value",
    }

    # Create a simple async iterator for the body
    async def chunk_iterator():
        yield b"data"

    mock_response.aiter_bytes.return_value = chunk_iterator()
    mock_response.aclose = AsyncMock()

    # Call the function under test
    streaming_response = _create_proxied_streaming_response(mock_response)

    # Verify the return type
    assert isinstance(streaming_response, StreamingResponse)
    assert streaming_response.status_code == 200
    # Hop-by-hop headers should be filtered out
    assert "content-length" not in streaming_response.headers
    assert "connection" not in streaming_response.headers
    # Other headers should be present
    assert streaming_response.headers["content-type"] == "application/json"
    assert streaming_response.headers["x-custom-header"] == "value"

    # Verify the streaming body works
    body_chunks = []
    async for chunk in streaming_response.body_iterator:
        body_chunks.append(chunk)
    assert body_chunks == [b"data"]

    # Ensure aclose is called when the stream ends (via finally block)
    mock_response.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_create_proxied_streaming_response_hop_by_hop_filtering():
    """
    Ensure all hop‑by‑hop headers defined in HOP_BY_HOP_HEADERS are filtered.
    """
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 204
    # Include every hop‑by‑hop header
    mock_response.headers = {
        "connection": "close",
        "keep-alive": "timeout=5",
        "proxy-authenticate": "Basic",
        "proxy-authorization": "Bearer xxx",
        "te": "trailers",
        "trailers": "ETag",
        "transfer-encoding": "chunked",
        "upgrade": "h2",
        "content-length": "0",
        "content-encoding": "gzip",
        "x-other": "should survive",
    }

    async def chunk_iterator():
        # No chunks
        if False:
            yield

    mock_response.aiter_bytes.return_value = chunk_iterator()
    mock_response.aclose = AsyncMock()

    streaming_response = _create_proxied_streaming_response(mock_response)

    # All hop‑by‑hop headers must be absent
    for key in mock_response.headers:
        if key.lower() in {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
            "content-length",
            "content-encoding",
        }:
            assert key.lower() not in {k.lower() for k in streaming_response.headers}
        else:
            assert key in streaming_response.headers
    # The only header left should be x-other
    assert list(streaming_response.headers.keys()) == ["x-other"]
    assert streaming_response.headers["x-other"] == "should survive"
