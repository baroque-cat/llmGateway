"""
Unit tests for UpstreamAttempt — frozen dataclass value object (test-plan section B).

Scenarios:
  B1  UpstreamAttempt is a frozen dataclass; modifying attributes raises FrozenInstanceError
  B2  Fields (response, check_result, body_bytes) accessible as attributes
  B3  Correct creation from (response, check_result, body_bytes) — 3-element tuple
  B11 forward_error() preserves original upstream status codes (401, 403, 429, 500, 503)
  B12 forward_error() delegates to forward_error_to_client() (mock verification)

Note: B4–B10 (discard/forward_error detailed behaviour) are covered by
test_response_forwarder.py and removed from this file to avoid duplication.
"""

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.response_forwarder import UpstreamAttempt

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
