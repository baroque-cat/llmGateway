"""
Unit tests for UpstreamAttempt — frozen dataclass value object (test-plan section B).

Scenarios:
  B1  UpstreamAttempt is a frozen dataclass; modifying attributes raises FrozenInstanceError
  B2  Fields (response, check_result, body_bytes) accessible as attributes
  B3  Correct creation from (response, check_result, body_bytes) — 3-element tuple
  B4  discard() calls aclose() when body_bytes=None
  B5  discard() is no-op when body_bytes is provided
  B6  discard() always returns None
  B7  forward_error() reads body via aread() when body_bytes=None, calls aclose() in finally
  B8  forward_error() uses pre-read body_bytes without calling aread()/aclose()
  B9  forward_error() filters hop-by-hop headers from the Response
  B10 forward_error() calls aclose() in finally even if aread() raises an exception
  B11 forward_error() preserves original upstream status codes (401, 403, 429, 500, 503)
  B12 forward_error() delegates to forward_error_to_client() (mock verification)
"""

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.response_forwarder import (
    UpstreamAttempt,
    _HOP_BY_HOP_HEADERS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(
    status_code: int = 503,
    headers: dict[str, str] | None = None,
    body: bytes = b"error body",
) -> AsyncMock:
    """Create an AsyncMock that mimics an httpx.Response."""
    response = AsyncMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = httpx.Headers(headers or {"content-type": "application/json"})
    response.aread = AsyncMock(return_value=body)
    response.aclose = AsyncMock()
    return response


def _make_check_result(
    available: bool = False,
    error_reason: ErrorReason = ErrorReason.RATE_LIMITED,
) -> CheckResult:
    """Create a CheckResult for testing."""
    if available:
        return CheckResult.success()
    return CheckResult.fail(error_reason)


# ---------------------------------------------------------------------------
# B1  Frozen dataclass enforcement
# ---------------------------------------------------------------------------


class TestUpstreamAttemptFrozenDataclass:
    """UpstreamAttempt must be a frozen dataclass — attribute mutation is forbidden."""

    def test_frozen_dataclass_raises_on_attribute_set(self) -> None:
        """Setting an attribute on a frozen UpstreamAttempt raises FrozenInstanceError."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            attempt.response = mock_response  # type: ignore[misc]

    def test_frozen_dataclass_raises_on_attribute_delete(self) -> None:
        """Deleting an attribute on a frozen UpstreamAttempt raises FrozenInstanceError."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            del attempt.response  # type: ignore[misc]

    def test_frozen_flag_is_true(self) -> None:
        """The dataclass __dataclass_params__.frozen must be True."""
        params = dataclasses.fields(UpstreamAttempt)
        # Verify the class itself is frozen
        assert UpstreamAttempt.__dataclass_params__.frozen is True


# ---------------------------------------------------------------------------
# B2  Fields accessible as attributes
# ---------------------------------------------------------------------------


class TestUpstreamAttemptFieldsAccessible:
    """All three fields must be accessible as plain attributes."""

    def test_response_accessible(self) -> None:
        """The response field stores the httpx.Response."""
        mock_response = _make_mock_response(status_code=429)
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        assert attempt.response is mock_response

    def test_check_result_accessible(self) -> None:
        """The check_result field stores the CheckResult."""
        mock_response = _make_mock_response()
        cr = _make_check_result(error_reason=ErrorReason.INVALID_KEY)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        assert attempt.check_result is cr
        assert attempt.check_result.error_reason == ErrorReason.INVALID_KEY

    def test_body_bytes_accessible_none(self) -> None:
        """The body_bytes field stores None when stream is still open."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        assert attempt.body_bytes is None

    def test_body_bytes_accessible_with_bytes(self) -> None:
        """The body_bytes field stores bytes when body is pre-read."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        body = b'{"error": "rate limited"}'
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        assert attempt.body_bytes == body


# ---------------------------------------------------------------------------
# B3  Construction from proxy_request() result tuple
# ---------------------------------------------------------------------------


class TestUpstreamAttemptConstructionFromTuple:
    """UpstreamAttempt can be constructed from the 3-element tuple
    returned by proxy_request(): (response, check_result, body_bytes)."""

    def test_constructed_from_three_element_tuple(self) -> None:
        """Creating UpstreamAttempt from (response, check_result, body_bytes) tuple works."""
        mock_response = _make_mock_response(status_code=403)
        cr = _make_check_result(error_reason=ErrorReason.NO_ACCESS)
        body = b"forbidden"

        # Simulate what proxy_request() returns
        proxy_result = (mock_response, cr, body)

        attempt = UpstreamAttempt(
            response=proxy_result[0],
            check_result=proxy_result[1],
            body_bytes=proxy_result[2],
        )

        assert attempt.response is proxy_result[0]
        assert attempt.check_result is proxy_result[1]
        assert attempt.body_bytes is proxy_result[2]

    def test_constructed_from_tuple_with_body_none(self) -> None:
        """Creating UpstreamAttempt from tuple with body_bytes=None (stream still open)."""
        mock_response = _make_mock_response(status_code=500)
        cr = _make_check_result(error_reason=ErrorReason.SERVER_ERROR)

        proxy_result = (mock_response, cr, None)

        attempt = UpstreamAttempt(
            response=proxy_result[0],
            check_result=proxy_result[1],
            body_bytes=proxy_result[2],
        )

        assert attempt.response is proxy_result[0]
        assert attempt.check_result is proxy_result[1]
        assert attempt.body_bytes is None


# ---------------------------------------------------------------------------
# B4  discard() calls aclose() when body_bytes=None
# ---------------------------------------------------------------------------


class TestDiscardCallsAcloseWhenBodyNone:
    """When body_bytes=None, discard() must close the response stream."""

    @pytest.mark.asyncio
    async def test_aclose_called_when_body_none(self) -> None:
        """discard() calls response.aclose() when body_bytes is None."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        await attempt.discard()

        mock_response.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# B5  discard() is no-op when body_bytes is provided
# ---------------------------------------------------------------------------


class TestDiscardNoopWhenBodyBytesProvided:
    """When body_bytes is already provided, discard() must NOT call aclose()."""

    @pytest.mark.asyncio
    async def test_aclose_not_called_when_body_bytes_present(self) -> None:
        """discard() does NOT call aclose() when body_bytes is not None."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=b"pre-read"
        )

        await attempt.discard()

        mock_response.aclose.assert_not_awaited()


# ---------------------------------------------------------------------------
# B6  discard() always returns None
# ---------------------------------------------------------------------------


class TestDiscardReturnsNoneAlways:
    """discard() must return None in both variants."""

    @pytest.mark.asyncio
    async def test_returns_none_when_body_none(self) -> None:
        """discard() returns None when body_bytes=None (calls aclose)."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        result = await attempt.discard()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_body_bytes_present(self) -> None:
        """discard() returns None when body_bytes is provided (no-op)."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=b"data"
        )

        result = await attempt.discard()
        assert result is None


# ---------------------------------------------------------------------------
# B7  forward_error() reads body when body_bytes=None
# ---------------------------------------------------------------------------


class TestForwardErrorReadsBodyWhenNone:
    """When body_bytes=None, forward_error() must read the body via aread()
    and close the response in finally, returning a Response with original
    status code and the read body."""

    @pytest.mark.asyncio
    async def test_aread_called_when_body_none(self) -> None:
        """forward_error() calls aread() when body_bytes is None."""
        mock_response = _make_mock_response(status_code=503, body=b"upstream error")
        cr = _make_check_result(error_reason=ErrorReason.SERVICE_UNAVAILABLE)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        result = await attempt.forward_error()

        mock_response.aread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aclose_called_in_finally_when_body_none(self) -> None:
        """forward_error() calls aclose() in finally block when body_bytes=None."""
        mock_response = _make_mock_response(status_code=503, body=b"upstream error")
        cr = _make_check_result(error_reason=ErrorReason.SERVICE_UNAVAILABLE)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        result = await attempt.forward_error()

        mock_response.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_response_with_original_status_and_body(self) -> None:
        """forward_error() returns Response with original status code and read body."""
        mock_response = _make_mock_response(
            status_code=503, body=b"upstream error body"
        )
        cr = _make_check_result(error_reason=ErrorReason.SERVICE_UNAVAILABLE)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        result = await attempt.forward_error()

        assert result.status_code == 503
        assert result.body == b"upstream error body"


# ---------------------------------------------------------------------------
# B8  forward_error() uses pre-read body_bytes
# ---------------------------------------------------------------------------


class TestForwardErrorUsesPreReadBody:
    """When body_bytes is already provided, forward_error() must NOT call
    aread() or aclose(), and must return a Response with the pre-read body."""

    @pytest.mark.asyncio
    async def test_aread_not_called_when_body_bytes_present(self) -> None:
        """forward_error() does NOT call aread() when body_bytes is provided."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        body = b"pre-read error body"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        result = await attempt.forward_error()

        mock_response.aread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_aclose_not_called_when_body_bytes_present(self) -> None:
        """forward_error() does NOT call aclose() when body_bytes is provided."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        body = b"pre-read error body"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        result = await attempt.forward_error()

        mock_response.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_response_with_body_bytes_and_status_code(self) -> None:
        """forward_error() returns Response with pre-read body_bytes and original status code."""
        mock_response = _make_mock_response(status_code=429)
        cr = _make_check_result(error_reason=ErrorReason.RATE_LIMITED)
        body = b"rate limited"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        result = await attempt.forward_error()

        assert result.status_code == 429
        assert result.body == b"rate limited"


# ---------------------------------------------------------------------------
# B9  forward_error() filters hop-by-hop headers
# ---------------------------------------------------------------------------


class TestForwardErrorFiltersHopByHopHeaders:
    """Hop-by-hop headers must be excluded from the forwarded Response."""

    @pytest.mark.asyncio
    async def test_hop_by_hop_headers_excluded(self) -> None:
        """forward_error() excludes all hop-by-hop headers from the Response.

        Note: FastAPI's Response auto-computes content-length from the body,
        so it may appear with a different value than the upstream's. We verify
        that the upstream's hop-by-hop values are not forwarded.
        """
        headers = {
            "content-type": "application/json",
            "connection": "keep-alive",
            "keep-alive": "timeout=60",
            "transfer-encoding": "chunked",
            "content-length": "123",
            "content-encoding": "gzip",
            "x-custom-header": "custom-value",
        }
        mock_response = _make_mock_response(
            status_code=503,
            headers=headers,
            body=b"error",
        )
        cr = _make_check_result()
        body = b"error"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        result = await attempt.forward_error()

        result_headers = dict(result.headers)

        # Hop-by-hop headers that FastAPI does NOT auto-add must be absent
        # (connection, keep-alive, transfer-encoding, content-encoding,
        #  proxy-authenticate, proxy-authorization, te, trailers, upgrade)
        auto_added_by_fastapi = {"content-length"}
        for hbh in _HOP_BY_HOP_HEADERS:
            if hbh in auto_added_by_fastapi:
                # FastAPI auto-computes content-length; verify the upstream
                # value ("123") was NOT forwarded — the result value should
                # be the actual body length
                assert (
                    result_headers.get(hbh) != "123"
                ), f"Upstream hop-by-hop header '{hbh}' value should be filtered"
            else:
                assert (
                    hbh not in result_headers
                ), f"Hop-by-hop header '{hbh}' should be filtered"

        # Non-hop-by-hop headers must be preserved
        assert "content-type" in result_headers
        assert "x-custom-header" in result_headers


# ---------------------------------------------------------------------------
# B10  forward_error() calls aclose() in finally even on aread() exception
# ---------------------------------------------------------------------------


class TestForwardErrorAcloseInFinallyOnAreadException:
    """If aread() throws an exception, aclose() must still be called
    in the finally block."""

    @pytest.mark.asyncio
    async def test_aclose_called_even_when_aread_raises(self) -> None:
        """aclose() is called in finally even if aread() raises an exception."""
        mock_response = _make_mock_response()
        mock_response.aread = AsyncMock(side_effect=httpx.ReadError("connection lost"))
        cr = _make_check_result(error_reason=ErrorReason.NETWORK_ERROR)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        # forward_error() should NOT raise — it catches the exception and
        # returns a fallback Response
        result = await attempt.forward_error()

        # aclose must have been called in the finally block
        mock_response.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_body_on_aread_exception(self) -> None:
        """When aread() fails, the Response body contains a fallback JSON error."""
        mock_response = _make_mock_response()
        mock_response.aread = AsyncMock(side_effect=httpx.ReadError("connection lost"))
        cr = _make_check_result(error_reason=ErrorReason.NETWORK_ERROR)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        result = await attempt.forward_error()

        # The fallback body should contain the error_reason value
        assert result.body is not None
        body_str = result.body.decode()
        assert "network_error" in body_str


# ---------------------------------------------------------------------------
# B11  forward_error() preserves original upstream status codes
# ---------------------------------------------------------------------------


class TestForwardErrorPreservesOriginalStatusCode:
    """Original upstream status codes (401, 403, 429, 500, 503) must be
    passed through unchanged."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status_code",
        [401, 403, 429, 500, 503],
        ids=[
            "401_unauthorized",
            "403_forbidden",
            "429_rate_limited",
            "500_server_error",
            "503_unavailable",
        ],
    )
    async def test_status_code_passed_through(self, status_code: int) -> None:
        """forward_error() returns Response with the original upstream status code."""
        mock_response = _make_mock_response(status_code=status_code)
        cr = _make_check_result()
        body = b"error response body"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        result = await attempt.forward_error()

        assert result.status_code == status_code


# ---------------------------------------------------------------------------
# B12  forward_error() delegates to forward_error_to_client()
# ---------------------------------------------------------------------------


class TestForwardErrorDelegatesToResponseForwarder:
    """forward_error() must internally delegate to forward_error_to_client()
    from response_forwarder.py."""

    @pytest.mark.asyncio
    async def test_forward_error_delegates_to_forward_error_to_client(self) -> None:
        """forward_error() calls forward_error_to_client() with the same arguments."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        body = b"error body"
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=body
        )

        with patch(
            "src.services.gateway.response_forwarder.forward_error_to_client",
            new=AsyncMock(return_value=MagicMock(spec=httpx.Response)),
        ) as mock_forward:
            result = await attempt.forward_error()

            mock_forward.assert_awaited_once_with(mock_response, cr, body)

    @pytest.mark.asyncio
    async def test_discard_delegates_to_discard_response(self) -> None:
        """discard() calls discard_response() with the same arguments."""
        mock_response = _make_mock_response()
        cr = _make_check_result()
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        with patch(
            "src.services.gateway.response_forwarder.discard_response",
            new=AsyncMock(return_value=None),
        ) as mock_discard:
            result = await attempt.discard()

            mock_discard.assert_awaited_once_with(mock_response, None)
