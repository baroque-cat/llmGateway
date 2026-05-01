# src/services/gateway/response_forwarder.py
"""
Centralized upstream response lifecycle management.

This module provides the single point of responsibility for transforming
upstream ``httpx.Response`` objects into FastAPI/Starlette responses returned
to the client.  It covers three scenarios:

* **Success** — wrap an open stream in a ``StreamMonitor`` and return a
  ``StreamingResponse`` (zero-overhead streaming).
* **Buffered body** — the response body has already been read (debug_mode
  or pre-parsed error); return a ``Response`` with the in-memory bytes.
* **Error forwarded to client** — the last attempt in a retry chain; read
  the body if needed, close the connection, and return the original
  upstream status code and body transparently.
* **Intermediate discard** — a failed attempt in a retry chain where the
  body is not needed; close the connection without reading the body
  (Zero-Overhead).

Public API:
    forward_success_stream(...) -> StreamingResponse
    forward_buffered_body(...) -> Response
    forward_error_to_client(...) -> Response
    discard_response(...) -> None
    UpstreamAttempt                  (frozen dataclass value object)
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from fastapi.responses import Response, StreamingResponse

if TYPE_CHECKING:
    from src.core.models import CheckResult

logger = logging.getLogger(__name__)

# -- Hop-by-hop headers that MUST NOT be forwarded to the client ----------
# These headers control the connection between two nodes (e.g. this proxy
# and the upstream).  Forwarding them would cause protocol conflicts.
_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
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
    }
)


def _extract_filtered_headers(response: httpx.Response) -> dict[str, str]:
    """Remove hop-by-hop headers from the upstream response.

    Returns a plain ``dict`` of headers that are safe to forward to the
    client.
    """
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }


async def forward_success_stream(
    upstream_response: httpx.Response,
    check_result: "CheckResult",
    client_ip: str,
    request_method: str,
    request_path: str,
    provider_name: str,
    model_name: str,
) -> StreamingResponse:
    """Forward a successful (2xx) upstream response as a stream.

    Creates a ``StreamMonitor`` to track the streaming lifecycle and wraps
    it in a ``StreamingResponse`` with filtered headers.  The upstream body
    is **not** read into memory — chunks are streamed directly to the
    client.
    """
    # Import here to avoid circular imports at module level.
    # StreamMonitor is used exclusively by the gateway → this forwarder.
    from src.services.gateway.gateway_service import StreamMonitor

    stream_monitor = StreamMonitor(
        upstream_response=upstream_response,
        client_ip=client_ip,
        request_method=request_method,
        request_path=request_path,
        provider_name=provider_name,
        model_name=model_name,
        check_result=check_result,
    )
    filtered_headers = _extract_filtered_headers(upstream_response)
    return StreamingResponse(
        content=stream_monitor,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type"),
        headers=filtered_headers,
    )


async def forward_buffered_body(
    upstream_response: httpx.Response,
    body_bytes: bytes | None = None,
    status_code_override: int | None = None,
) -> Response:
    """Return a buffered ``Response`` with the upstream body already in memory.

    If *body_bytes* is not provided, the body is read from the upstream via
    :meth:`httpx.Response.aread`.  The connection is always closed
    afterwards (``finally`` block).

    Args:
        upstream_response: The raw upstream response.
        body_bytes: Pre-read body bytes (optional).  If ``None``, the body
            will be read now.
        status_code_override: If set, override the upstream status code.

    Returns:
        A FastAPI ``Response`` with the (filtered) headers and body.
    """
    status_code = (
        status_code_override
        if status_code_override is not None
        else upstream_response.status_code
    )

    if body_bytes is None:
        try:
            body_bytes = await upstream_response.aread()
        except Exception:
            logger.error("Failed to read upstream body", exc_info=True)
            body_bytes = b""
        finally:
            await upstream_response.aclose()

    filtered_headers = _extract_filtered_headers(upstream_response)
    return Response(
        content=body_bytes,
        status_code=status_code,
        headers=filtered_headers,
    )


async def forward_error_to_client(
    upstream_response: httpx.Response,
    check_result: "CheckResult",
    body_bytes: bytes | None,
) -> Response:
    """Forward the **original** upstream error response to the client.

    This function is called on the **last** attempt in a retry chain.
    If the body has not been pre-read (*body_bytes* is ``None``) it is
    read now.  The original upstream status code and body are preserved
    transparently.

    Args:
        upstream_response: The raw upstream response.
        check_result: Parsed check result (currently unused but accepted
            for consistency).
        body_bytes: Pre-read body bytes, or ``None`` to read now.

    Returns:
        A ``Response`` with the original upstream status code and body,
        with hop-by-hop headers removed.
    """
    if body_bytes is None:
        try:
            body_bytes = await upstream_response.aread()
        except Exception:
            logger.error("Failed to read upstream error body", exc_info=True)
            body_bytes = f'{{"error": "Upstream error: {check_result.error_reason.value}"}}'.encode()
        finally:
            await upstream_response.aclose()

    filtered_headers = _extract_filtered_headers(upstream_response)
    return Response(
        content=body_bytes,
        status_code=upstream_response.status_code,
        headers=filtered_headers,
    )


async def discard_response(
    upstream_response: httpx.Response,
    body_bytes: bytes | None,
) -> None:
    """Close an upstream response connection without reading the body.

    Used for **intermediate** attempts in a retry cycle where the body is
    not needed (Zero-Overhead).  If *body_bytes* is already present the
    connection was closed by ``aread()`` and this is a safe no-op.

    Args:
        upstream_response: The raw upstream response.
        body_bytes: Pre-read body (or ``None`` if stream is still open).
    """
    if body_bytes is None:
        # Stream is still open — close it without reading.
        await upstream_response.aclose()
    # else: connection already closed by aread() → no-op


# ---------------------------------------------------------------------------
# Value object: UpstreamAttempt
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UpstreamAttempt:
    """Encapsulates the result of a single upstream proxy attempt.

    A frozen dataclass that groups the three values returned by
    :meth:`provider.proxy_request` into a single value object with
    intent-revealing methods.

    Fields:
        response: The raw ``httpx.Response`` from the upstream provider.
        check_result: Parsed ``CheckResult`` (success or failure).
        body_bytes: Pre-read body (``None`` when the stream is still open).
    """

    response: httpx.Response
    check_result: "CheckResult"
    body_bytes: bytes | None

    async def discard(self) -> None:
        """Close the connection without reading the body (Zero-Overhead).

        Delegates to :func:`discard_response`.
        """
        await discard_response(self.response, self.body_bytes)

    async def forward_error(self) -> Response:
        """Forward the original upstream error to the client.

        Delegates to :func:`forward_error_to_client`.
        """
        return await forward_error_to_client(
            self.response, self.check_result, self.body_bytes
        )
