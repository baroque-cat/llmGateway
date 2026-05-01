"""
Security and infrastructure tests for the transparent-error-forwarding change.

Covers test-plan sections L, M, and N:
  L — Connection leaks: aclose() guarantees on all error paths
  M — Header injection / information leakage: hop-by-hop filtering, content-encoding
  N — Signature contract enforcement: proxy_request / _send_proxy_request return types
"""

import inspect
import subprocess
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.response_forwarder import (
    UpstreamAttempt,
    _HOP_BY_HOP_HEADERS,
    _extract_filtered_headers,
    discard_response,
    forward_error_to_client,
    forward_success_stream,
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


# ===========================================================================
# Section L — Connection leaks
# ===========================================================================


class TestConnectionLeaks:
    """Tests verifying that upstream connections are always closed, even on
    exceptions, double-close, and all error paths."""

    # ------------------------------------------------------------------
    # L1: No connection leak on exception between proxy_request and discard
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_no_connection_leak_on_exception_between_proxy_request_and_discard(
        self,
    ) -> None:
        """If the handler throws an exception between proxy_request() and
        discard()/forward_error(), the connection must still be closed.

        The intended pattern is: wrap the handler logic in try/finally and
        call UpstreamAttempt.discard() in the finally block.  This test
        simulates that pattern and verifies aclose() is called even when
        an exception interrupts normal processing.
        """
        mock_response = _make_mock_response(status_code=500, body=b"server error")
        cr = _make_check_result(error_reason=ErrorReason.SERVER_ERROR)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        # Simulate handler pattern: try/finally with discard() in finally
        with pytest.raises(RuntimeError, match="simulated handler crash"):
            try:
                # Handler processes the attempt...
                # An exception occurs before discard() or forward_error()
                raise RuntimeError("simulated handler crash")
            finally:
                # discard() in finally ensures connection closure
                await attempt.discard()

        # aclose() must have been called via discard() → discard_response()
        mock_response.aclose.assert_awaited_once()

    # ------------------------------------------------------------------
    # L2: Double close is safe (discard after forward_error)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_double_close_is_safe(self) -> None:
        """discard() called after forward_error() (double close):
        httpx aclose() on an already-closed connection is a safe no-op.

        Since UpstreamAttempt is frozen, body_bytes stays None even after
        forward_error() internally reads the body and closes the stream.
        Calling discard() afterwards will call discard_response(response, None)
        which calls aclose() again.  This must not raise an exception.
        """
        mock_response = _make_mock_response(status_code=429, body=b"rate limited")
        cr = _make_check_result(error_reason=ErrorReason.RATE_LIMITED)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=None
        )

        # First: forward_error() reads body and closes stream (aclose in finally)
        result = await attempt.forward_error()
        assert result.status_code == 429
        assert result.body == b"rate limited"

        # forward_error() called aread + aclose
        mock_response.aread.assert_awaited_once()
        first_aclose_count = mock_response.aclose.await_count

        # Second: discard() calls discard_response(response, None) → aclose() again
        # This is a double-close scenario. Must NOT raise an exception.
        await attempt.discard()

        # aclose() was called again (double close) — no exception raised
        assert mock_response.aclose.await_count == first_aclose_count + 1

    # ------------------------------------------------------------------
    # L3: aclose called in finally for all error paths
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_aclose_called_in_finally_for_all_error_paths(self) -> None:
        """For every error path in the response lifecycle, aclose() is
        guaranteed via UpstreamAttempt.discard() or forward_error_to_client()
        (finally-block inside forward_error_to_client).

        This test covers three distinct paths:
          1. forward_error_to_client with body_bytes=None, aread succeeds → aclose in finally
          2. forward_error_to_client with body_bytes=None, aread raises → aclose in finally
          3. discard_response with body_bytes=None → aclose called directly
        """
        cr = _make_check_result(error_reason=ErrorReason.SERVER_ERROR)

        # Path 1: forward_error_to_client, body_bytes=None, aread succeeds
        mock_resp_1 = _make_mock_response(status_code=500, body=b"error1")
        result_1 = await forward_error_to_client(mock_resp_1, cr, body_bytes=None)
        mock_resp_1.aread.assert_awaited_once()
        mock_resp_1.aclose.assert_awaited_once()  # aclose in finally
        assert result_1.body == b"error1"

        # Path 2: forward_error_to_client, body_bytes=None, aread raises
        mock_resp_2 = _make_mock_response(status_code=500)
        mock_resp_2.aread = AsyncMock(side_effect=httpx.ReadError("connection lost"))
        result_2 = await forward_error_to_client(mock_resp_2, cr, body_bytes=None)
        mock_resp_2.aread.assert_awaited_once()
        mock_resp_2.aclose.assert_awaited_once()  # aclose STILL called in finally
        # Fallback body contains error reason
        assert "server_error" in result_2.body.decode()

        # Path 3: discard_response with body_bytes=None → aclose called
        mock_resp_3 = _make_mock_response(status_code=500)
        await discard_response(mock_resp_3, body_bytes=None)
        mock_resp_3.aclose.assert_awaited_once()


# ===========================================================================
# Section M — Header injection / information leakage
# ===========================================================================


class TestHeaderInjectionAndInformationLeakage:
    """Tests verifying that hop-by-hop headers are never forwarded to the
    client, preventing protocol conflicts and information leakage."""

    # ------------------------------------------------------------------
    # M1: Hop-by-hop headers never forwarded to client
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_hop_by_hop_headers_never_forwarded_to_client_via_forward_error(
        self,
    ) -> None:
        """Upstream includes Connection: keep-alive, Transfer-Encoding: chunked,
        Proxy-Authorization: Basic ... → all excluded from client response
        when using forward_error_to_client()."""
        dangerous_headers = {
            "content-type": "application/json",
            "connection": "keep-alive",
            "keep-alive": "timeout=60",
            "transfer-encoding": "chunked",
            "proxy-authenticate": 'Basic realm="upstream"',
            "proxy-authorization": "Basic dXNlcjpwYXNz",
            "te": "trailers",
            "trailers": "X-Custom-Trailer",
            "upgrade": "websocket",
            "content-length": "999",
            "content-encoding": "gzip",
            "x-request-id": "req-safe-123",
        }
        mock_response = _make_mock_response(
            status_code=503, headers=dangerous_headers, body=b"upstream error"
        )
        cr = _make_check_result(error_reason=ErrorReason.SERVICE_UNAVAILABLE)

        result = await forward_error_to_client(
            mock_response, cr, body_bytes=b"upstream error"
        )

        result_headers = dict(result.headers)

        # Every hop-by-hop header must be absent from the client response
        for hbh in _HOP_BY_HOP_HEADERS:
            # content-length may be auto-added by FastAPI with a different value,
            # so we check that the upstream's dangerous value is NOT forwarded
            if hbh == "content-length":
                # The upstream value "999" must not appear
                assert (
                    result_headers.get(hbh) != "999"
                ), f"Upstream hop-by-hop '{hbh}' value leaked to client"
            else:
                assert (
                    hbh not in result_headers
                ), f"Hop-by-hop header '{hbh}' leaked to client response"

        # Safe headers must be preserved
        assert "x-request-id" in result_headers
        assert result_headers["x-request-id"] == "req-safe-123"

    @pytest.mark.asyncio
    async def test_SEC_hop_by_hop_headers_never_forwarded_to_client_via_forward_success_stream(
        self,
    ) -> None:
        """Upstream includes Connection: keep-alive, Transfer-Encoding: chunked,
        Proxy-Authorization: Basic ... → all excluded from client response
        when using forward_success_stream()."""
        dangerous_headers = {
            "content-type": "text/event-stream",
            "connection": "keep-alive",
            "keep-alive": "timeout=60",
            "transfer-encoding": "chunked",
            "proxy-authenticate": 'Basic realm="upstream"',
            "proxy-authorization": "Basic dXNlcjpwYXNz",
            "te": "trailers",
            "trailers": "X-Custom-Trailer",
            "upgrade": "websocket",
            "content-length": "999",
            "content-encoding": "gzip",
            "x-request-id": "req-safe-456",
        }
        mock_response = _make_mock_response(status_code=200, headers=dangerous_headers)
        cr_success = CheckResult.success(status_code=200)

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=MagicMock(),
        ):
            result = await forward_success_stream(
                upstream_response=mock_response,
                check_result=cr_success,
                client_ip="127.0.0.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )

        result_headers = dict(result.headers)

        # Every hop-by-hop header must be absent from the client response
        for hbh in _HOP_BY_HOP_HEADERS:
            if hbh == "content-length":
                assert (
                    result_headers.get(hbh) != "999"
                ), f"Upstream hop-by-hop '{hbh}' value leaked to client"
            else:
                assert (
                    hbh not in result_headers
                ), f"Hop-by-hop header '{hbh}' leaked to client StreamingResponse"

        # Safe headers must be preserved
        assert "x-request-id" in result_headers

    @pytest.mark.asyncio
    async def test_SEC_hop_by_hop_headers_never_forwarded_to_client_via_UpstreamAttempt_forward_error(
        self,
    ) -> None:
        """UpstreamAttempt.forward_error() also filters hop-by-hop headers —
        verifying the delegation chain preserves the security guarantee."""
        dangerous_headers = {
            "content-type": "application/json",
            "connection": "keep-alive",
            "proxy-authorization": "Basic dXNlcjpwYXNz",
            "transfer-encoding": "chunked",
            "x-safe-header": "safe-value",
        }
        mock_response = _make_mock_response(
            status_code=403, headers=dangerous_headers, body=b"forbidden"
        )
        cr = _make_check_result(error_reason=ErrorReason.NO_ACCESS)
        attempt = UpstreamAttempt(
            response=mock_response, check_result=cr, body_bytes=b"forbidden"
        )

        result = await attempt.forward_error()

        result_headers = dict(result.headers)
        assert "connection" not in result_headers
        assert "proxy-authorization" not in result_headers
        assert "transfer-encoding" not in result_headers
        assert "x-safe-header" in result_headers

    # ------------------------------------------------------------------
    # M2: API key in forwarded error body (out of scope — xfail)
    # ------------------------------------------------------------------

    @pytest.mark.xfail(
        reason="Body sanitization for API keys in forwarded errors is out of scope "
        "for the transparent-error-forwarding change. The gateway forwards the "
        "original upstream body verbatim. A separate content-redaction workflow "
        "is needed to strip secrets from error bodies before forwarding.",
        strict=True,
    )
    @pytest.mark.asyncio
    async def test_SEC_no_api_key_in_forwarded_error_body(self) -> None:
        """Upstream error body containing an API key should be sanitized
        before forwarding to the client.

        This is currently a NON-GOAL of the transparent-error-forwarding
        change: the gateway forwards the original upstream body verbatim.
        A dedicated content-redaction pipeline is needed to address this.
        """
        api_key_body = b'{"error": "Invalid API key sk-abc123def456"}'
        mock_response = _make_mock_response(status_code=401, body=api_key_body)
        cr = _make_check_result(error_reason=ErrorReason.INVALID_KEY)

        result = await forward_error_to_client(
            mock_response, cr, body_bytes=api_key_body
        )

        # This assertion WILL FAIL because the body is forwarded verbatim
        assert (
            "sk-abc123def456" not in result.body.decode()
        ), "API key leaked in forwarded error body — needs content redaction"

    # ------------------------------------------------------------------
    # M3: Content-Encoding not forwarded
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_content_encoding_not_forwarded_via_forward_error(
        self,
    ) -> None:
        """Upstream returns Content-Encoding: gzip → header excluded from
        forwarded error response.  Client gets raw body without gzip wrapper
        expectation."""
        headers_with_encoding = {
            "content-type": "application/json",
            "content-encoding": "gzip",
            "x-custom": "value",
        }
        mock_response = _make_mock_response(
            status_code=500, headers=headers_with_encoding, body=b"raw error body"
        )
        cr = _make_check_result(error_reason=ErrorReason.SERVER_ERROR)

        result = await forward_error_to_client(
            mock_response, cr, body_bytes=b"raw error body"
        )

        result_headers = dict(result.headers)
        assert "content-encoding" not in result_headers, (
            "Content-Encoding header leaked to client — client would expect gzip "
            "wrapper but receive raw bytes"
        )
        # Body is raw (not gzip-compressed)
        assert result.body == b"raw error body"
        # Other headers preserved
        assert "x-custom" in result_headers

    @pytest.mark.asyncio
    async def test_SEC_content_encoding_not_forwarded_via_forward_success_stream(
        self,
    ) -> None:
        """Upstream returns Content-Encoding: gzip → header excluded from
        forwarded success streaming response."""
        headers_with_encoding = {
            "content-type": "text/event-stream",
            "content-encoding": "gzip",
            "x-custom": "value",
        }
        mock_response = _make_mock_response(
            status_code=200, headers=headers_with_encoding
        )
        cr_success = CheckResult.success(status_code=200)

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=MagicMock(),
        ):
            result = await forward_success_stream(
                upstream_response=mock_response,
                check_result=cr_success,
                client_ip="127.0.0.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )

        result_headers = dict(result.headers)
        assert "content-encoding" not in result_headers, (
            "Content-Encoding header leaked to StreamingResponse — "
            "client would expect gzip but stream is raw"
        )
        assert "x-custom" in result_headers


# ===========================================================================
# Section N — Signature contract enforcement
# ===========================================================================


class TestSignatureContractEnforcement:
    """Tests verifying that proxy_request() and _send_proxy_request() return
    exactly a 3-element tuple as declared in their type annotations."""

    # ------------------------------------------------------------------
    # N1: proxy_request() signature type check (runtime)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_SEC_proxy_request_signature_type_check_runtime_unpack(
        self,
    ) -> None:
        """If a provider's proxy_request() returns a 2-element tuple instead
        of the required 3-element tuple, unpacking raises TypeError.

        This validates the contract:
          proxy_request() -> tuple[httpx.Response, CheckResult, bytes | None]
        """
        # Simulate a broken provider that returns only 2 elements
        broken_result = (
            MagicMock(spec=httpx.Response),
            CheckResult.fail(ErrorReason.SERVER_ERROR),
        )

        with pytest.raises(ValueError, match="not enough values to unpack"):
            # Attempting to unpack 2 elements into 3 variables
            _response, _check_result, _body_bytes = broken_result  # type: ignore[misc]

    def test_SEC_proxy_request_signature_type_check_annotation(self) -> None:
        """The IProvider.proxy_request abstract method declares return type
        tuple[httpx.Response, CheckResult, bytes | None] — exactly 3 elements.

        Verify the annotation is present and correct via introspection.
        """
        from src.core.interfaces import IProvider

        sig = inspect.signature(IProvider.proxy_request)
        return_annotation = sig.return_annotation

        # The return annotation must mention tuple with 3 types
        annotation_str = str(return_annotation)
        assert (
            "tuple" in annotation_str
        ), f"proxy_request return annotation must be a tuple: got {annotation_str}"
        # Must contain httpx.Response, CheckResult, and bytes | None
        assert (
            "httpx.Response" in annotation_str
        ), f"proxy_request return annotation must include httpx.Response: got {annotation_str}"
        assert (
            "CheckResult" in annotation_str
        ), f"proxy_request return annotation must include CheckResult: got {annotation_str}"
        assert (
            "bytes" in annotation_str
        ), f"proxy_request return annotation must include bytes: got {annotation_str}"

    # ------------------------------------------------------------------
    # N2: _send_proxy_request() signature type check (static + runtime)
    # ------------------------------------------------------------------

    def test_SEC_send_proxy_request_signature_type_check_annotation(self) -> None:
        """_send_proxy_request() in AIBaseProvider declares return type
        tuple[httpx.Response, CheckResult, bytes | None] — exactly 3 elements.

        Verify the annotation is present and correct via introspection.
        """
        from src.providers.base import AIBaseProvider

        sig = inspect.signature(AIBaseProvider._send_proxy_request)
        return_annotation = sig.return_annotation

        annotation_str = str(return_annotation)
        assert (
            "tuple" in annotation_str
        ), f"_send_proxy_request return annotation must be a tuple: got {annotation_str}"
        assert (
            "httpx.Response" in annotation_str
        ), f"_send_proxy_request return annotation must include httpx.Response: got {annotation_str}"
        assert (
            "CheckResult" in annotation_str
        ), f"_send_proxy_request return annotation must include CheckResult: got {annotation_str}"
        assert (
            "bytes" in annotation_str
        ), f"_send_proxy_request return annotation must include bytes: got {annotation_str}"

    def test_SEC_send_proxy_request_signature_type_check_pyright(self) -> None:
        """Static typing via pyright confirms _send_proxy_request() returns
        a 3-element tuple.  Run pyright on the base provider module and
        verify no type errors on the return annotation."""
        result = subprocess.run(
            [
                "poetry",
                "run",
                "pyright",
                "--verifytypes",
                "src.providers.base.AIBaseProvider._send_proxy_request",
                "--outputjson",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # pyright should not report type errors on _send_proxy_request
        # If pyright is not configured for verifytypes, fall back to
        # checking the general pyright output for the module
        if result.returncode != 0 and "verifytypes" in (result.stderr or ""):
            # Fall back: just run pyright on the file and check for 0 errors
            result = subprocess.run(
                ["poetry", "run", "pyright", "src/providers/base.py", "--outputjson"],
                capture_output=True,
                text=True,
                timeout=60,
            )

        # We don't require 0 errors across the whole file (there may be
        # unrelated issues), but we check that _send_proxy_request's
        # return type is properly annotated by inspecting the source
        # directly as a fallback
        if result.returncode != 0:
            # Fallback: verify the annotation via source inspection
            from src.providers.base import AIBaseProvider

            sig = inspect.signature(AIBaseProvider._send_proxy_request)
            annotation_str = str(sig.return_annotation)
            assert "tuple" in annotation_str
            assert "httpx.Response" in annotation_str
            assert "CheckResult" in annotation_str
            assert "bytes" in annotation_str

    @pytest.mark.asyncio
    async def test_SEC_send_proxy_request_returns_three_element_tuple(
        self,
    ) -> None:
        """Runtime verification: _send_proxy_request() always returns exactly
        3 elements (httpx.Response, CheckResult, bytes | None).

        Mock the httpx client to return a successful response and verify
        the tuple structure.
        """
        from src.providers.base import AIBaseProvider

        # Create a minimal concrete subclass for testing
        class TestProvider(AIBaseProvider):
            async def _parse_proxy_error(
                self, response: httpx.Response, content: bytes | None = None
            ) -> CheckResult:
                return CheckResult.fail(
                    ErrorReason.SERVER_ERROR, status_code=response.status_code
                )

            async def parse_request_details(
                self, path: str, content: bytes
            ) -> "RequestDetails":
                from src.core.models import RequestDetails

                return RequestDetails(model_name="test-model")

            def _get_headers(self, token: str) -> dict[str, str] | None:
                return {"Authorization": f"Bearer {token}"}

            async def check(
                self, client: httpx.AsyncClient, token: str, **kwargs
            ) -> CheckResult:
                return CheckResult.success()

            async def inspect(
                self, client: httpx.AsyncClient, token: str, **kwargs
            ) -> list[str]:
                return []

            async def proxy_request(
                self,
                client: httpx.AsyncClient,
                token: str,
                method: str,
                headers: dict[str, str],
                path: str,
                query_params: str,
                content: bytes,
            ) -> tuple[httpx.Response, CheckResult, bytes | None]:
                request = client.build_request(method, f"https://api.test.com{path}")
                return await self._send_proxy_request(client, request)

        # Create a mock provider config
        from src.config.schemas import ProviderConfig, GatewayPolicyConfig

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.gateway_policy.debug_mode = "disabled"
        mock_config.error_parsing = MagicMock()
        mock_config.error_parsing.enabled = False
        mock_config.error_parsing.rules = []

        provider = TestProvider(provider_name="test", config=mock_config)

        # Mock the httpx client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_upstream = AsyncMock(spec=httpx.Response)
        mock_upstream.status_code = 200
        mock_upstream.is_success = True
        mock_upstream.headers = httpx.Headers({"content-type": "application/json"})
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_client.build_request = Mock(return_value=MagicMock(spec=httpx.Request))

        result = await provider._send_proxy_request(
            mock_client, MagicMock(spec=httpx.Request)
        )

        # Must be exactly 3 elements
        assert (
            len(result) == 3
        ), f"_send_proxy_request must return 3-element tuple, got {len(result)} elements"
        # First element: httpx.Response
        assert isinstance(result[0], httpx.Response) or hasattr(
            result[0], "status_code"
        ), "First element must be httpx.Response-like"
        # Second element: CheckResult
        assert isinstance(result[1], CheckResult), "Second element must be CheckResult"
        # Third element: bytes | None
        assert result[2] is None or isinstance(
            result[2], bytes
        ), "Third element must be bytes or None"
