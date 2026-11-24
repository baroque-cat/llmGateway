# src/services/gateway_service.py

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

# Import core application components
from src.config.schemas import NetworkGuardConfig, RetryOnErrorConfig
from src.core.accessor import ConfigAccessor
from src.core.constants import (  # Added explicitly for error type checking
    ALL_MODELS_MARKER,
    ErrorReason,
    KeySelectionMode,
)
from src.core.http_client_factory import HttpClientFactory
from src.core.interfaces import IProvider
from src.core.models import CheckResult
from src.core.network_guard import NetworkGuard, set_network_guard
from src.core.policy_utils import compute_next_check_time
from src.db import database
from src.db.database import DatabaseManager
from src.metrics import emit_guard_transition
from src.metrics.auth import (
    MetricsAuthError,
    validate_metrics_access,
    validate_metrics_token,
)
from src.providers import get_provider
from src.services.gateway.gateway_cache import GatewayCache, observe_upstream_attempt
from src.services.gateway.response_forwarder import (
    discard_response,
    forward_buffered_body,
    forward_error_to_client,
    forward_success_stream,
)

# --- Dependency Injection Helpers ---
# These functions provide a typed and safe way to access app state,
# replacing the direct `request.app.state` pattern which is unsafe for static analysis.


def _get_db_manager(request: Request) -> DatabaseManager:
    """Retrieves the DatabaseManager from the application state."""
    return request.app.state.db_manager


def _get_gateway_cache(request: Request) -> GatewayCache:
    """Retrieves the GatewayCache from the application state."""
    return request.app.state.gateway_cache


def _get_http_client_factory(request: Request) -> HttpClientFactory:
    """Retrieves the HttpClientFactory from the application state."""
    return request.app.state.http_client_factory


def _get_config_accessor(request: Request) -> ConfigAccessor:
    """Retrieves the ConfigAccessor from the application state."""
    return request.app.state.accessor


def _observe_attempt(
    request: Request, provider_name: str, check_result: CheckResult
) -> None:
    """Emit attempt metrics and feed transport failures to the outage guard.

    Args:
        request: Current FastAPI request (for app state access).
        provider_name: Provider instance name.
        check_result: Result of the upstream attempt.
    """
    observe_upstream_attempt(provider_name, check_result)
    if check_result.transport_class is None:
        return
    guard = getattr(request.app.state, "network_guard", None)
    if isinstance(guard, NetworkGuard):
        guard.note_failure(provider_name, check_result.transport_class)


# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the application's state and dependencies.
# It is populated during the FastAPI startup event.
app_state: dict[str, Any] = {
    "accessor": None,
    "db_manager": None,
    "http_client_factory": None,
    "gateway_cache": None,
    "cache_refresh_task": None,
}

# --- Helper Functions ---


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    Sanitizes sensitive headers to prevent secret leakage in logs.
    Replaces the values of known sensitive headers with '***'.
    """
    sensitive_headers = {"authorization", "x-goog-api-key", "x-api-key"}
    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in sensitive_headers:
            # For Authorization, keep the scheme (e.g., 'Bearer') but mask the token
            if key.lower() == "authorization" and value.startswith("Bearer "):
                sanitized[key] = "Bearer ***"
            else:
                sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_body(body: bytes, provider_type: str | None = None) -> str:
    """
    Sanitizes the request/response body for logging in debug mode.
    Attempts to parse as JSON and redact known sensitive fields.
    Handles SSE (Server-Sent Events) payloads correctly by parsing
    individual ``data:`` lines as JSON and applying redaction separately.
    Falls back to safe decoding if parsing fails.

    Args:
        body: Raw request or response body bytes.
        provider_type: Optional provider type string for content redaction
            in ``no_content`` mode. Passed through to ``redact_content()``.

    Returns:
        Sanitized string representation of the body.
    """
    try:
        decoded_str = body.decode("utf-8")

        # Detect SSE payloads: body contains "data: " lines
        if "data: " in decoded_str:
            events = decoded_str.split("\n\n")
            sanitized_events: list[str] = []
            for event in events:
                lines = event.split("\n")
                sanitized_lines: list[str] = []
                for line in lines:
                    if line.startswith("data: "):
                        json_str = line.removeprefix("data: ")
                        try:
                            # Parse JSON to validate, re-serialize, and apply regex
                            parsed = json.loads(json_str)
                            serialized = json.dumps(parsed)
                            redacted = re.sub(
                                r'("api[_-]?key"|"token"|"secret"|"password")\s*:\s*"[^"]*"',
                                r'\1: "***"',
                                serialized,
                                flags=re.IGNORECASE,
                            )
                            line = f"data: {redacted}"
                        except (json.JSONDecodeError, TypeError):
                            # Malformed JSON inside data: — leave line as-is
                            pass
                    sanitized_lines.append(line)
                sanitized_events.append("\n".join(sanitized_lines))
            return "\n\n".join(sanitized_events)

        # Plain JSON fast path
        if decoded_str.strip().startswith(("{", "[")):
            # Simple regex-based redaction for common sensitive keys
            # This is a best-effort approach and may not catch all cases.
            redacted_str = re.sub(
                r'("api[_-]?key"|"token"|"secret"|"password")\s*:\s*"[^"]*"',
                r'\1: "***"',
                decoded_str,
                flags=re.IGNORECASE,
            )
            return redacted_str
        else:
            return decoded_str
    except (UnicodeDecodeError, json.JSONDecodeError):
        # If it's not valid UTF-8 or not JSON, use repr to show a safe representation
        return repr(body)


class GatewayStreamError(Exception):
    """
    Domain exception raised when a streaming connection is dropped
    (``httpx.ReadError``) while reading a response from an upstream provider.

    Attributes:
        provider_name: Name of the provider instance where the disconnect occurred.
        model_name: Name of the model the request was targeting.
        error_reason: ``ErrorReason.STREAM_DISCONNECT`` constant.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_name: str,
        model_name: str,
        error_reason: ErrorReason = ErrorReason.STREAM_DISCONNECT,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.error_reason = error_reason
        super().__init__(message)


class StreamMonitor:
    """
    An async generator wrapper to monitor and log streaming responses.
    It measures the total duration of the stream and logs a final transaction summary.
    """

    def __init__(
        self,
        upstream_response: httpx.Response,
        client_ip: str,
        request_method: str,
        request_path: str,
        provider_name: str,
        model_name: str,
        check_result: CheckResult | None = None,
    ):
        self.upstream_response = upstream_response
        self.client_ip = client_ip
        self.request_method = request_method
        self.request_path = request_path
        self.provider_name = provider_name
        self.model_name = model_name
        self.check_result = check_result
        self.start_time = None
        self._finalized: bool = False
        # Initialize the stream iterator once to avoid StreamConsumed error
        self.stream_iterator = upstream_response.aiter_bytes()

    def _get_internal_status(self) -> str:
        """Determines the internal status string for logging."""
        if self.check_result and not self.check_result.ok:
            return self.check_result.error_reason.value.upper()
        elif self.upstream_response.status_code == 200:
            return "VALID"
        else:
            return "UNKNOWN"

    def _format_model_name(self) -> str:
        """Formats the model name for logging, replacing ALL_MODELS_MARKER with 'shared'."""
        from src.core.constants import ALL_MODELS_MARKER

        if self.model_name == ALL_MODELS_MARKER:
            return "shared"
        return self.model_name

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.start_time is None:
            self.start_time = asyncio.get_event_loop().time()
        # Track whether this call ends the stream (exception/completion)
        # vs. returns a chunk normally (stream continues). On normal chunk
        # return, finally must NOT finalize — the stream is still active.
        _stream_ended = True
        try:
            chunk = await self.stream_iterator.__anext__()
            _stream_ended = False
            return chunk
        except StopAsyncIteration:
            # Normal stream completion — finalize in finally
            raise
        except httpx.ReadError as e:
            # Upstream provider disconnected the stream prematurely.
            # Log with provider/model context and raise a domain exception
            # so the gateway can return a controlled error instead of a 500.
            logger.warning(
                f"Upstream stream disconnect for provider '{self.provider_name}' "
                f"model '{self.model_name}': {e}"
            )
            raise GatewayStreamError(
                f"Stream disconnected by upstream provider '{self.provider_name}'",
                provider_name=self.provider_name,
                model_name=self.model_name,
            ) from e
        finally:
            if _stream_ended and not self._finalized:
                await self._finalize_logging()

    async def _finalize_logging(self):
        """Logs the final transaction summary after the stream is complete or failed."""
        if self._finalized:
            return
        self._finalized = True
        if self.start_time is None:
            return  # The stream never started

        duration = asyncio.get_event_loop().time() - self.start_time
        formatted_model = self._format_model_name()
        internal_status = self._get_internal_status()
        http_status = f"{self.upstream_response.status_code} {self.upstream_response.reason_phrase}"

        logger.info(
            f"GATEWAY_ACCESS | {self.client_ip} -> {self.request_method} {self.request_path} | "
            f"{self.provider_name}:{formatted_model} | {http_status} -> {internal_status} ({duration:.2f}s)"
        )
        # Ensure the upstream connection is closed.
        try:
            await self.upstream_response.aclose()
        except Exception:
            logger.error(
                "Failed to close upstream response for provider "
                f"'{self.provider_name}'",
                exc_info=True,
            )


# --- Helper Functions ---


def _log_debug_info(
    debug_mode: str,
    instance_name: str,
    request_method: str,
    request_path: str,
    request_headers: dict[str, str],
    request_body: bytes,
    response_status: int,
    response_headers: dict[str, str],
    response_body: bytes,
    provider_type: str | None = None,
) -> None:
    """
    Logs debug information based on the debug mode setting.

    Args:
        debug_mode: The effective debug mode (``"no_content"`` or ``"full_body"``).
        instance_name: The name of the provider instance.
        request_method: HTTP method of the request.
        request_path: Path of the request.
        request_headers: Headers from the client request.
        request_body: Body content from the client request (pre-sanitized).
        response_status: HTTP status code from the upstream response.
        response_headers: Headers from the upstream response.
        response_body: Body content from the upstream response (pre-sanitized).
        provider_type: Provider type string for content redaction in ``no_content`` mode.
    """
    # Sanitize headers before logging
    sanitized_request_headers = _sanitize_headers(request_headers)
    sanitized_response_headers = _sanitize_headers(response_headers)

    # Log basic request info
    logger.info(f"Request to {instance_name}: {request_method} {request_path}")
    logger.info(f"Request headers: {sanitized_request_headers}")

    # Log request body if in full_body or no_content mode
    if debug_mode in ("full_body", "no_content"):
        decoded_request_body = _sanitize_body(request_body, provider_type)
        # Collapse newlines for single-line log output
        safe_body = decoded_request_body.replace("\n", "\\n").replace("\r", "\\r")
        logger.info(f"Request body: {safe_body}")

    # Log response info
    logger.info(f"Response from {instance_name}: {response_status}")
    logger.info(f"Response headers: {sanitized_response_headers}")

    # Log response body if in full_body or no_content mode
    if debug_mode in ("full_body", "no_content"):
        decoded_response_body = _sanitize_body(response_body, provider_type)
        # Collapse newlines for single-line log output
        safe_body = decoded_response_body.replace("\n", "\\n").replace("\r", "\\r")
        logger.info(f"Response body: {safe_body}")


async def _report_key_failure(
    db_manager: DatabaseManager,
    key_id: int,
    provider_name: str,
    result: CheckResult,
    accessor: ConfigAccessor,
) -> None:
    """
    A fire-and-forget background task to report a key failure to the database.
    This implements the "fast feedback loop".

    Computes ``next_check_time`` from the provider's ``HealthPolicyConfig``
    based on the error reason, respecting the configured cooldown intervals.

    In transparent proxy mode, model_name is always ALL_MODELS_MARKER since
    the gateway no longer tracks per-model key status.

    Transport-level failures are deliberately ignored: a dead tunnel or
    connection reset is not evidence that the key is bad.
    """
    if result.transport_class is not None:
        logger.debug(
            f"Fast feedback: skipping key {key_id} penalty for transport "
            f"failure ({result.transport_class.value})."
        )
        return

    try:
        provider_config = accessor.get_provider_or_raise(provider_name)
        health_policy = provider_config.worker_health_policy
        hp = health_policy
        next_check = compute_next_check_time(
            result.error_reason,
            on_no_quota_hr=hp.on_no_quota_hr,
            on_rate_limit_hr=hp.on_rate_limit_hr,
            on_invalid_key_days=hp.on_invalid_key_days,
            on_no_access_days=hp.on_no_access_days,
            on_server_error_min=hp.on_server_error_min,
            on_overload_min=hp.on_overload_min,
            on_other_error_hr=hp.on_other_error_hr,
        )
        await db_manager.keys.update_status(
            key_id=key_id,
            model_name=ALL_MODELS_MARKER,
            provider_name=provider_name,
            result=result,
            next_check_time=next_check,
        )
        logger.debug(
            f"Fast feedback: Successfully reported failure for key_id {key_id} to the database."
        )
    except Exception as e:
        logger.error(
            f"Fast feedback: Failed to report key failure for key_id {key_id}.",
            exc_info=e,
        )


async def _cache_refresh_loop(cache: GatewayCache, interval_sec: int) -> None:
    """
    An infinite loop that periodically refreshes the key pool cache.
    """
    logger.info(
        f"Starting cache refresh loop with an interval of {interval_sec} seconds."
    )
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await cache.refresh_key_pool()
        except asyncio.CancelledError:
            logger.info("Cache refresh loop is shutting down.")
            break
        except Exception:
            logger.error("An error occurred in the cache refresh loop.", exc_info=True)


async def _pool_health_log_loop(factory: HttpClientFactory, interval_sec: int) -> None:
    """Periodically log HTTP pool health summaries at INFO level.

    Args:
        factory: The ``HttpClientFactory`` that owns the cached clients.
        interval_sec: Seconds between log iterations.
    """
    logger.info(
        f"Starting pool health log loop with an interval of {interval_sec} seconds."
    )
    while True:
        try:
            await asyncio.sleep(interval_sec)
            summaries = factory.get_pool_health_summary()
            if not summaries:
                logger.info("HTTP_POOL_HEALTH | no active clients")
                continue
            for cache_key, summary in summaries.items():
                logger.info(
                    "HTTP_POOL_HEALTH | %s | conns: %d total (%d active, %d idle) | "
                    "proto: %d H2 / %d H1 | "
                    "streams: %d active / %d max_capacity | "
                    "queued: %d",
                    cache_key,
                    _health_int(summary, "total_connections"),
                    _health_int(summary, "active_connections"),
                    _health_int(summary, "idle_connections"),
                    _health_int(summary, "h2_connections"),
                    _health_int(summary, "h1_connections"),
                    _health_int(summary, "active_h2_streams"),
                    _health_int(summary, "max_h2_stream_capacity"),
                    _health_int(summary, "queued_requests"),
                )
                # Per-connection breakdown
                raw_conns = summary.get("connections")
                conn_list: list[dict[str, int | str]] = (
                    raw_conns if isinstance(raw_conns, list) else []
                )
                for conn_info in conn_list:
                    logger.info(
                        "HTTP_POOL_CONN | %s | %s | %s | %s | streams: %s/%s",
                        cache_key,
                        conn_info.get("label", ""),
                        conn_info.get("state", ""),
                        conn_info.get("protocol", ""),
                        conn_info.get("active_streams", 0),
                        conn_info.get("max_streams", 0),
                    )
        except asyncio.CancelledError:
            logger.info("Pool health log loop is shutting down.")
            break
        except Exception:
            logger.error(
                "An error occurred in the pool health log loop.", exc_info=True
            )


def _health_int(summary: dict[str, int | list[dict[str, int | str]]], key: str) -> int:
    """Extract an int value from a health summary dict.

    Args:
        summary: A pool health summary dict with mixed int/list values.
        key: The key to look up.

    Returns:
        The int value for ``key``, or ``0`` if not present or not an int.
    """
    val = summary.get(key, 0)
    return val if isinstance(val, int) else 0


def _get_token_from_headers(
    authorization: Annotated[str | None, Header()] = None,
    x_goog_api_key: Annotated[str | None, Header()] = None,
) -> str | None:
    """
    Extracts the API token from request headers with a defined priority.
    1. Checks for 'Authorization: Bearer <token>'.
    2. Falls back to 'x-goog-api-key: <token>'.
    """
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return x_goog_api_key


async def _handle_full_stream_request(
    request: Request, provider: IProvider, instance_name: str
) -> Response:
    """
    Handles requests where both request and response can be streamed (full-duplex).
    Does NOT read the request body into memory.

    In transparent proxy mode, model_name is set to ALL_MODELS_MARKER since the
    gateway no longer validates or inspects model names.
    """
    cache = _get_gateway_cache(request)
    http_factory = _get_http_client_factory(request)
    db_manager = _get_db_manager(request)
    accessor = _get_config_accessor(request)

    # Sticky-mode wiring (design D11). In round-robin mode both flags are
    # False and the handler behaves exactly as before this change.
    sticky = cache.get_selection_mode(instance_name) is KeySelectionMode.STICKY
    fail_fast = cache.should_fail_fast(instance_name) if sticky else False

    key_info = cache.get_key_from_pool(instance_name)
    if not key_info:
        logger.warning(f"No valid API keys available in pool for '{instance_name}'.")
        return JSONResponse(
            status_code=503, content={"error": "No available API keys."}
        )

    key_id, api_key = key_info
    client = await http_factory.get_client_for_provider(instance_name)

    upstream_response, check_result, body_bytes = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request.method,
        headers=dict(request.headers),
        path=request.url.path,
        query_params=str(request.url.query),
        content=request.stream(),
    )
    _observe_attempt(request, instance_name, check_result)

    if sticky:
        # Feed the attempt outcome to the circuit breaker. No-op when the
        # breaker is disabled.
        cache.record_upstream_result(
            instance_name, check_result.ok, check_result.error_reason, key_info
        )

    if check_result.ok:
        # Case 1: Success. Stream the response back to the client using StreamMonitor.
        client_ip = request.client.host if request.client else "unknown"
        return await forward_success_stream(
            upstream_response=upstream_response,
            check_result=check_result,
            client_ip=client_ip,
            request_method=request.method,
            request_path=str(request.url),
            provider_name=instance_name,
            model_name=ALL_MODELS_MARKER,
        )

    elif check_result.error_reason.is_client_error():
        # Case 2: Client-side error (e.g., 400 Bad Request). The key is not at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to a client-side error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) will NOT be penalized. Forwarding original error to client."
        )
        return await forward_error_to_client(
            upstream_response, check_result, body_bytes
        )

    else:
        # Case 3: Upstream or key-related error.
        reason = check_result.error_reason
        sticky_rotate_without_ban = (
            sticky
            and not fail_fast
            and reason.is_server_error()
            and reason is not ErrorReason.OVERLOADED
        )

        if sticky_rotate_without_ban:
            logger.warning(
                f"Request for '{instance_name}' failed with a server error: [{reason.value}]. "
                f"Sticky key (ID: {key_id}) rotates WITHOUT a penalty (the provider, not the key, is at fault)."
            )
        elif sticky and fail_fast and not reason.is_fatal():
            logger.warning(
                f"Request for '{instance_name}' failed during fail-fast: [{reason.value}]. "
                f"Upstream error forwarded transparently; key (ID: {key_id}) ban frozen while the breaker is OPEN."
            )
        else:
            logger.warning(
                f"Request for '{instance_name}' failed due to an upstream/key error: [{reason.value}]. "
                f"The API key (ID: {key_id}) WILL be penalized."
            )

        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )
        if effective_debug_mode != "disabled":
            if body_bytes is None:
                body_bytes = await upstream_response.aread()
            _log_debug_info(
                debug_mode=effective_debug_mode,
                instance_name=instance_name,
                request_method=request.method,
                request_path=str(request.url),
                request_headers=dict(request.headers),
                request_body=b"",  # We don't have the original request body in full stream mode
                response_status=upstream_response.status_code,
                response_headers=dict(upstream_response.headers),
                response_body=body_bytes,
            )

        if sticky:
            if fail_fast:
                # Breaker OPEN fail-fast: ban freeze — retryable errors do
                # NOT penalize the key; fatal errors still ban (design D7).
                if reason.is_fatal():
                    asyncio.create_task(
                        _report_key_failure(
                            db_manager, key_id, instance_name, check_result, accessor
                        )
                    )
                    asyncio.create_task(
                        cache.remove_key_from_pool(instance_name, key_id)
                    )
            elif sticky_rotate_without_ban:
                # Server error: rotate the sticky pointer WITHOUT banning the
                # key in the database and WITHOUT removing it from the pool
                # (design D4).
                cache.rotate_sticky_key(instance_name, exclude_key_ids={key_id})
                cache.note_rotation_without_ban(instance_name)
            else:
                # Fatal / OVERLOADED / RATE_LIMITED: rotate + ban (as today).
                asyncio.create_task(
                    _report_key_failure(
                        db_manager, key_id, instance_name, check_result, accessor
                    )
                )
                asyncio.create_task(cache.remove_key_from_pool(instance_name, key_id))
                cache.rotate_sticky_key(instance_name, exclude_key_ids={key_id})
        else:
            # Round-robin: report and remove the failed key from the live
            # cache (unchanged behavior).
            asyncio.create_task(
                _report_key_failure(
                    db_manager, key_id, instance_name, check_result, accessor
                )
            )
            asyncio.create_task(cache.remove_key_from_pool(instance_name, key_id))

        return await forward_error_to_client(
            upstream_response, check_result, body_bytes
        )


async def _handle_buffered_retryable_request(
    request: Request, provider: IProvider, instance_name: str
) -> Response:
    """
    Handles requests where retry is enabled. Requires buffering the request body.
    Streams the response on the first successful attempt.
    """
    cache = _get_gateway_cache(request)
    http_factory = _get_http_client_factory(request)
    db_manager = _get_db_manager(request)
    accessor = _get_config_accessor(request)

    provider_config = accessor.get_provider_or_raise(instance_name)
    retry_policy = provider_config.gateway_policy.retry
    key_error_policy = retry_policy.on_key_error
    server_error_policy = retry_policy.on_server_error
    transport_error_policy = retry_policy.on_transport_error
    # Tests and older configs may provide a mocked/legacy retry policy without
    # the new field; fall back to "no transport retries" rather than guessing.
    if not isinstance(transport_error_policy, RetryOnErrorConfig):
        transport_error_policy = RetryOnErrorConfig(attempts=0)

    # Debug mode forces the buffered path and, per the startup warning, takes
    # priority over the retry policy.  Honour both that warning and
    # ``retry.enabled=false`` by zeroing the attempt budgets, so a debug
    # session never silently retries.
    effective_debug_mode = request.app.state.debug_mode_map.get(
        instance_name, "disabled"
    )
    if not retry_policy.enabled or effective_debug_mode != "disabled":
        key_error_policy = key_error_policy.model_copy(update={"attempts": 0})
        server_error_policy = server_error_policy.model_copy(update={"attempts": 0})
        transport_error_policy = transport_error_policy.model_copy(
            update={"attempts": 0}
        )

    # Sticky-mode wiring (design D5). In round-robin mode both flags are
    # False and the retry loop below behaves exactly as before this change.
    sticky = (
        provider_config.gateway_policy.key_selection.mode is KeySelectionMode.STICKY
    )
    fail_fast = cache.should_fail_fast(instance_name) if sticky else False

    request_body = await request.body()
    try:
        _ = await provider.parse_request_details(
            path=request.url.path, content=request_body
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

    failed_key_ids: set[int] = set()
    total_attempts = 0
    key_error_attempts = 0
    server_error_attempts = 0
    transport_error_attempts = 0
    evicted_providers: set[str] = set()
    last_reason: ErrorReason | None = None

    timeout_sec = provider_config.timeouts.total
    # Guard against mocked configs in tests where timeout values may be MagicMock
    # rather than a real float (pyright sees the annotated type, not the runtime type).
    if not isinstance(
        timeout_sec, (int, float)
    ):  # pyright: ignore[reportUnnecessaryIsInstance]
        timeout_sec = 600.0

    # Hoisted to function scope so they are accessible in the finally block
    # for guaranteed upstream response closure on timeout (Design Decision 4).
    upstream_response: httpx.Response | None = None
    body_bytes: bytes | None = None
    _response_handled = False

    try:
        async with asyncio.timeout(timeout_sec):
            # The fail-fast and sticky branches below always terminate with a
            # return. When neither applies, execution falls through to the
            # original round-robin loop, which is intentionally kept unchanged.
            if fail_fast:
                # Breaker OPEN (design D7): bypass the retry loop. Exactly one
                # upstream attempt; the upstream error is forwarded to the
                # client transparently; bans are frozen for retryable errors
                # (fatal errors still ban).
                key_info = cache.get_key_from_pool(instance_name)
                if not key_info:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": "No available API keys to handle the request."
                        },
                    )

                key_id, api_key = key_info
                total_attempts += 1
                client = await http_factory.get_client_for_provider(instance_name)

                upstream_response, check_result, body_bytes = (
                    await provider.proxy_request(
                        client=client,
                        token=api_key,
                        method=request.method,
                        headers=dict(request.headers),
                        path=request.url.path,
                        query_params=str(request.url.query),
                        content=request_body,
                    )
                )
                _response_handled = False
                _observe_attempt(request, instance_name, check_result)
                cache.record_upstream_result(
                    instance_name,
                    check_result.ok,
                    check_result.error_reason,
                    key_info,
                )

                if check_result.ok:
                    effective_debug_mode = request.app.state.debug_mode_map.get(
                        instance_name, "disabled"
                    )
                    if effective_debug_mode != "disabled":
                        _response_handled = True
                        return await forward_buffered_body(
                            upstream_response, body_bytes
                        )
                    client_ip = request.client.host if request.client else "unknown"
                    _response_handled = True
                    return await forward_success_stream(
                        upstream_response=upstream_response,
                        check_result=check_result,
                        client_ip=client_ip,
                        request_method=request.method,
                        request_path=str(request.url),
                        provider_name=instance_name,
                        model_name=ALL_MODELS_MARKER,
                    )

                reason = check_result.error_reason
                last_reason = reason
                logger.warning(
                    f"Fail-fast attempt {total_attempts} failed for '{instance_name}'. "
                    f"Reason: [{reason.value}], Key: #{key_id}, "
                    f"Status: {upstream_response.status_code}. "
                    f"Forwarding upstream error transparently (breaker OPEN)."
                )

                # Ban freeze while OPEN: retryable errors do not penalize the
                # key; fatal errors still ban (design D7).
                if reason.is_fatal():
                    asyncio.create_task(
                        _report_key_failure(
                            db_manager, key_id, instance_name, check_result, accessor
                        )
                    )
                    asyncio.create_task(
                        cache.remove_key_from_pool(instance_name, key_id)
                    )

                effective_debug_mode = request.app.state.debug_mode_map.get(
                    instance_name, "disabled"
                )
                if effective_debug_mode != "disabled":
                    _response_handled = True
                    return await forward_buffered_body(upstream_response, body_bytes)
                _response_handled = True
                return await forward_error_to_client(
                    upstream_response, check_result, body_bytes
                )

            elif sticky:
                # Sticky retry loop (design D5): every rotation trigger
                # (fatal errors, OVERLOADED, RATE_LIMITED, and server errors)
                # excludes the failed key, consumes on_key_error attempts, and
                # retries the REQUEST with a NEW key. The same-key
                # on_server_error branch is never executed in sticky mode and
                # server errors never ban the key (design D4).
                while True:
                    total_attempts += 1
                    key_info = cache.get_key_from_pool(
                        instance_name, exclude_key_ids=failed_key_ids
                    )
                    if not key_info:
                        return JSONResponse(
                            status_code=503,
                            content={
                                "error": "No available API keys to handle the request."
                            },
                        )

                    key_id, api_key = key_info
                    client = await http_factory.get_client_for_provider(instance_name)

                    upstream_response, check_result, body_bytes = (
                        await provider.proxy_request(
                            client=client,
                            token=api_key,
                            method=request.method,
                            headers=dict(request.headers),
                            path=request.url.path,
                            query_params=str(request.url.query),
                            content=request_body,
                        )
                    )
                    _response_handled = False
                    _observe_attempt(request, instance_name, check_result)
                    cache.record_upstream_result(
                        instance_name,
                        check_result.ok,
                        check_result.error_reason,
                        key_info,
                    )

                    if check_result.ok:
                        # Case 1: Success. Check if debug logging is needed.
                        effective_debug_mode = request.app.state.debug_mode_map.get(
                            instance_name, "disabled"
                        )

                        if effective_debug_mode != "disabled":
                            _response_handled = True
                            return await forward_buffered_body(
                                upstream_response, body_bytes
                            )
                        else:
                            # Normal streaming response when debug is disabled
                            client_ip = (
                                request.client.host if request.client else "unknown"
                            )
                            _response_handled = True
                            return await forward_success_stream(
                                upstream_response=upstream_response,
                                check_result=check_result,
                                client_ip=client_ip,
                                request_method=request.method,
                                request_path=str(request.url),
                                provider_name=instance_name,
                                model_name=ALL_MODELS_MARKER,
                            )

                    reason = check_result.error_reason
                    last_reason = reason
                    logger.warning(
                        f"Attempt {total_attempts} failed for '{instance_name}'. "
                        f"Reason: [{reason.value}], "
                        f"Key: #{key_id}, "
                        f"Status: {upstream_response.status_code}"
                    )
                    logger.info(
                        f"Retry status (sticky) - Total attempts: {total_attempts}, "
                        f"Key errors: {key_error_attempts}/{key_error_policy.attempts}"
                    )

                    if check_result.transport_class is not None:
                        # Transport failure: the key is not at fault. Rotate to
                        # another key for this request, but never ban it.
                        transport_error_attempts += 1
                        logger.warning(
                            f"Transport failure for '{instance_name}' "
                            f"(class={check_result.transport_class.value}, "
                            f"attempt {transport_error_attempts}/"
                            f"{transport_error_policy.attempts}). "
                            f"Key #{key_id} is NOT penalized."
                        )
                        if transport_error_attempts < transport_error_policy.attempts:
                            # The key is not at fault and all keys share the
                            # same tunnel, so retry the same key with a fresh
                            # HTTP client instead of exhausting the pool.
                            await discard_response(upstream_response, body_bytes)
                            _response_handled = True
                            delay = transport_error_policy.backoff_sec * (
                                transport_error_policy.backoff_factor
                                ** (transport_error_attempts - 1)
                            )
                            if instance_name not in evicted_providers:
                                evicted_providers.add(instance_name)
                                await http_factory.evict(instance_name)
                            logger.info(
                                f"Transport retry in {delay:.2f}s with a fresh "
                                f"connection (attempt {transport_error_attempts}/"
                                f"{transport_error_policy.attempts})..."
                            )
                            await asyncio.sleep(delay)
                            continue

                        logger.error(
                            f"Exhausted all {transport_error_policy.attempts} "
                            f"transport retry attempts for '{instance_name}'. "
                            f"Key #{key_id} is not penalized; forwarding the error."
                        )
                        _response_handled = True
                        return await forward_error_to_client(
                            upstream_response, check_result, body_bytes
                        )

                    if reason.is_client_error():
                        # Case 2: Client-side error. Retrying is pointless.
                        # Abort the loop without consuming counters; the
                        # sticky pointer is not changed.
                        logger.error(
                            f"Non-retryable client error received: {reason.value}. Aborting retry cycle."
                        )
                        effective_debug_mode = request.app.state.debug_mode_map.get(
                            instance_name, "disabled"
                        )
                        if effective_debug_mode != "disabled":
                            _response_handled = True
                            return await forward_buffered_body(
                                upstream_response, body_bytes
                            )

                        _response_handled = True
                        return await forward_error_to_client(
                            upstream_response, check_result, body_bytes
                        )

                    # Case 3: Rotation trigger. Fatal errors, OVERLOADED,
                    # RATE_LIMITED, and server errors all exclude the failed
                    # key and retry the REQUEST with a NEW key.
                    failed_key_ids.add(key_id)

                    if (
                        reason.is_server_error()
                        and reason is not ErrorReason.OVERLOADED
                    ):
                        # Server error: rotate WITHOUT ban — the provider, not
                        # the key, is at fault (design D4). No
                        # _report_key_failure, no remove_key_from_pool.
                        cache.note_rotation_without_ban(instance_name)
                        logger.warning(
                            f"Sticky rotation without ban for key_id {key_id} "
                            f"(Reason: {reason.value})."
                        )
                    else:
                        # Fatal / OVERLOADED / RATE_LIMITED: ban and remove.
                        logger.warning(
                            f"Key fault detected (Reason: {reason.value}). "
                            f"Marking key_id {key_id} as failed and removing from pool."
                        )
                        asyncio.create_task(
                            _report_key_failure(
                                db_manager,
                                key_id,
                                instance_name,
                                check_result,
                                accessor,
                            )
                        )
                        asyncio.create_task(
                            cache.remove_key_from_pool(instance_name, key_id)
                        )

                    key_error_attempts += 1

                    if key_error_attempts < key_error_policy.attempts:
                        # Intermediate attempt: discard and retry with next key
                        await discard_response(upstream_response, body_bytes)
                        _response_handled = True
                        delay = key_error_policy.backoff_sec * (
                            key_error_policy.backoff_factor ** (key_error_attempts - 1)
                        )
                        logger.info(
                            f"Rotating key... Backoff {delay:.2f}s. (Key Error Attempt {key_error_attempts}/{key_error_policy.attempts})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(
                            f"Exhausted all {key_error_policy.attempts} retry attempts for key errors."
                        )
                        _response_handled = True
                        return await forward_error_to_client(
                            upstream_response, check_result, body_bytes
                        )

            while True:
                total_attempts += 1
                key_info = cache.get_key_from_pool(
                    instance_name, exclude_key_ids=failed_key_ids
                )
                if not key_info:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": "No available API keys to handle the request."
                        },
                    )

                key_id, api_key = key_info
                client = await http_factory.get_client_for_provider(instance_name)

                upstream_response, check_result, body_bytes = (
                    await provider.proxy_request(
                        client=client,
                        token=api_key,
                        method=request.method,
                        headers=dict(request.headers),
                        path=request.url.path,
                        query_params=str(request.url.query),
                        content=request_body,
                    )
                )
                _response_handled = False
                _observe_attempt(request, instance_name, check_result)

                if check_result.ok:
                    # Case 1: Success. Check if debug logging is needed.
                    effective_debug_mode = request.app.state.debug_mode_map.get(
                        instance_name, "disabled"
                    )

                    if effective_debug_mode != "disabled":
                        _response_handled = True
                        return await forward_buffered_body(
                            upstream_response, body_bytes
                        )
                    else:
                        # Normal streaming response when debug is disabled
                        client_ip = request.client.host if request.client else "unknown"
                        _response_handled = True
                        return await forward_success_stream(
                            upstream_response=upstream_response,
                            check_result=check_result,
                            client_ip=client_ip,
                            request_method=request.method,
                            request_path=str(request.url),
                            provider_name=instance_name,
                            model_name=ALL_MODELS_MARKER,
                        )

                reason = check_result.error_reason
                last_reason = reason
                logger.warning(
                    f"Attempt {total_attempts} failed for '{instance_name}'. "
                    f"Reason: [{reason.value}], "
                    f"Key: #{key_id}, "
                    f"Status: {upstream_response.status_code}"
                )
                logger.info(
                    f"Retry status - Total attempts: {total_attempts}, Key errors: {key_error_attempts}/{key_error_policy.attempts}, "
                    f"Server errors (current key): {server_error_attempts}/{server_error_policy.attempts}"
                )

                if check_result.transport_class is not None:
                    # Transport failure: do not charge it to the key and do not
                    # consume the server-error budget. Rotate for this request.
                    transport_error_attempts += 1
                    logger.warning(
                        f"Transport failure for '{instance_name}' "
                        f"(class={check_result.transport_class.value}, "
                        f"attempt {transport_error_attempts}/"
                        f"{transport_error_policy.attempts}). "
                        f"Key #{key_id} is NOT penalized."
                    )
                    if transport_error_attempts < transport_error_policy.attempts:
                        # Keep the key: the tunnel, not the key, failed.
                        await discard_response(upstream_response, body_bytes)
                        _response_handled = True
                        delay = transport_error_policy.backoff_sec * (
                            transport_error_policy.backoff_factor
                            ** (transport_error_attempts - 1)
                        )
                        if instance_name not in evicted_providers:
                            evicted_providers.add(instance_name)
                            await http_factory.evict(instance_name)
                        logger.info(
                            f"Transport retry in {delay:.2f}s with a fresh "
                            f"connection (attempt {transport_error_attempts}/"
                            f"{transport_error_policy.attempts})..."
                        )
                        await asyncio.sleep(delay)
                        continue

                    logger.error(
                        f"Exhausted all {transport_error_policy.attempts} "
                        f"transport retry attempts for '{instance_name}'. "
                        f"Key #{key_id} is not penalized; forwarding the error."
                    )
                    _response_handled = True
                    return await forward_error_to_client(
                        upstream_response, check_result, body_bytes
                    )

                if reason.is_client_error():
                    # Case 2: Client-side error. Retrying is pointless. Abort the loop.
                    logger.error(
                        f"Non-retryable client error received: {reason.value}. Aborting retry cycle."
                    )
                    effective_debug_mode = request.app.state.debug_mode_map.get(
                        instance_name, "disabled"
                    )
                    if effective_debug_mode != "disabled":
                        _response_handled = True
                        return await forward_buffered_body(
                            upstream_response, body_bytes
                        )

                    _response_handled = True
                    return await forward_error_to_client(
                        upstream_response, check_result, body_bytes
                    )

                # Case 3: Key-specific failures OR Overloaded (503).
                if (not reason.is_retryable()) or (reason == ErrorReason.OVERLOADED):
                    # Add to local blacklist to prevent fetching the same broken key again
                    failed_key_ids.add(key_id)

                    logger.warning(
                        f"Key fault detected (Reason: {reason.value}). "
                        f"Marking key_id {key_id} as failed and removing from pool."
                    )

                    asyncio.create_task(
                        _report_key_failure(
                            db_manager,
                            key_id,
                            instance_name,
                            check_result,
                            accessor,
                        )
                    )
                    asyncio.create_task(
                        cache.remove_key_from_pool(instance_name, key_id)
                    )

                    key_error_attempts += 1
                    server_error_attempts = 0

                    if key_error_attempts < key_error_policy.attempts:
                        # Intermediate attempt: discard and retry with next key
                        await discard_response(upstream_response, body_bytes)
                        _response_handled = True
                        delay = key_error_policy.backoff_sec * (
                            key_error_policy.backoff_factor ** (key_error_attempts - 1)
                        )
                        logger.info(
                            f"Rotating key... Backoff {delay:.2f}s. (Key Error Attempt {key_error_attempts}/{key_error_policy.attempts})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(
                            f"Exhausted all {key_error_policy.attempts} retry attempts for key errors."
                        )
                        _response_handled = True
                        return await forward_error_to_client(
                            upstream_response, check_result, body_bytes
                        )

                # Case 4: True Transient Server Errors (Timeout, Connection Error, etc).
                elif reason.is_retryable():
                    server_error_attempts += 1
                    if server_error_attempts < server_error_policy.attempts:
                        # Intermediate server error attempt: discard and retry
                        await discard_response(upstream_response, body_bytes)
                        _response_handled = True
                        delay = server_error_policy.backoff_sec * (
                            server_error_policy.backoff_factor
                            ** (server_error_attempts - 1)
                        )
                        logger.info(
                            f"Server error detected. Retrying in {delay:.2f}s... (Server Error Attempt {server_error_attempts}/{server_error_policy.attempts})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.warning(
                            f"Exhausted all {server_error_policy.attempts} retry attempts for server errors. Penalizing key {key_id}."
                        )

                        # Add to local blacklist
                        failed_key_ids.add(key_id)

                        # Treat exhaustion as a key failure: Penalize and Rotate
                        asyncio.create_task(
                            _report_key_failure(
                                db_manager,
                                key_id,
                                instance_name,
                                check_result,
                                accessor,
                            )
                        )
                        asyncio.create_task(
                            cache.remove_key_from_pool(instance_name, key_id)
                        )

                        # Fall through to Key Rotation logic
                        key_error_attempts += 1
                        server_error_attempts = 0

                        if key_error_attempts < key_error_policy.attempts:
                            await discard_response(upstream_response, body_bytes)
                            _response_handled = True
                            delay = key_error_policy.backoff_sec * (
                                key_error_policy.backoff_factor
                                ** (key_error_attempts - 1)
                            )
                            logger.info(
                                f"Rotating key after server retry exhaustion... Backoff {delay:.2f}s."
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            _response_handled = True
                            return await forward_error_to_client(
                                upstream_response, check_result, body_bytes
                            )

    except TimeoutError:
        last_reason_str = last_reason.value if last_reason else "unknown"
        logger.error(
            f"Request to '{instance_name}' timed out after {timeout_sec:.0f}s "
            f"(total attempts: {total_attempts}, "
            f"key_errors: {key_error_attempts}, "
            f"server_errors: {server_error_attempts}). "
            f"Last error: [{last_reason_str}]."
        )
        return JSONResponse(
            status_code=504,
            content={
                "error": (
                    f"Gateway timeout: upstream request did not complete "
                    f"within {timeout_sec:.0f}s"
                ),
                "attempts": total_attempts,
                "last_error": last_reason_str,
            },
        )
    finally:
        if upstream_response is not None and not _response_handled:
            try:
                await discard_response(upstream_response, body_bytes)
            except Exception:
                logger.error(
                    "Failed to discard upstream response after timeout "
                    f"for provider '{instance_name}'",
                    exc_info=True,
                )


# --- FastAPI Application Factory and Event Handlers ---


def create_app(accessor: ConfigAccessor) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- Startup Logic ---
        logger.info("Gateway service starting up...")
        guard_task: asyncio.Task[None] | None = None
        try:
            # Store the accessor in the app state for other components to use.
            app.state.accessor = accessor

            # Global outage guard.  It starts before any provider work and, if
            # its startup probe fails, keeps the gateway paused (503) instead
            # of burning keys against a dead network.
            guard_config = accessor.get_network_guard_config()
            if not isinstance(guard_config, NetworkGuardConfig):
                # Test/legacy accessor double without the new section.
                guard_config = NetworkGuardConfig()
            guard = NetworkGuard(
                guard_config,
                source="gateway",
                on_transition=emit_guard_transition,
            )
            app.state.network_guard = guard
            set_network_guard(guard)
            await guard.startup_probe()
            emit_guard_transition(
                "down" if guard.is_down() else "up", {"reason": "startup"}
            )
            if guard.enabled:
                guard_task = asyncio.create_task(guard.poll_loop())
                app.state.network_guard_task = guard_task

            # This block implements the requested feature for detailed startup logging.
            logger.info("[Gateway Startup] Analyzing provider streaming modes...")

            # Initialize data structures for the dispatcher logic.
            full_stream_instances: set[str] = set()
            debug_mode_map: dict[str, str] = {}  # Track debug mode per provider

            # Iterate through all enabled providers to analyze and log their mode.
            for name, config in accessor.get_enabled_providers().items():
                mode = ""
                reason = ""

                # Determine the effective debug mode for this provider.
                effective_debug_mode = config.gateway_policy.debug_mode

                # Store the effective debug mode for use during request handling.
                debug_mode_map[name] = effective_debug_mode

                # Warn if both debug mode and retry are configured
                if (
                    effective_debug_mode != "disabled"
                    and config.gateway_policy.retry.enabled
                ):
                    logger.warning(
                        f"[Gateway Startup] Instance '{name}': Retry policy is CONFIGURED but "
                        f"WILL BE IGNORED because debug mode '{effective_debug_mode}' takes priority. "
                        f"Disable debug mode to restore retry behavior."
                    )

                # Determine the effective streaming mode for this provider.
                effective_streaming_mode = config.gateway_policy.streaming_mode

                # If debug mode is enabled, force buffered requests.
                if effective_debug_mode != "disabled":
                    mode = "DEBUG MODE"
                    reason = f"Debug mode '{effective_debug_mode}' enabled - forcing buffered requests"
                # If retry is enabled, force buffered requests.
                elif config.gateway_policy.retry.enabled:
                    mode = "PARTIAL STREAM"
                    reason = "Retry policy is enabled"
                # Streaming explicitly disabled.
                elif effective_streaming_mode == "disabled":
                    mode = "PARTIAL STREAM"
                    reason = "Streaming is explicitly disabled"
                # Default: full-stream transparent proxy for all instances.
                else:
                    mode = "FULL STREAM"
                    reason = "Transparent proxy mode - all requests forwarded without buffering"
                    full_stream_instances.add(name)

                # Log the determined mode and reason for operational clarity.
                logger.info(
                    f"[Gateway Startup] - Instance '{name}' -> {mode} (Reason: {reason})"
                )

            logger.info("[Gateway Startup] Analysis complete.")

            dsn = accessor.get_database_dsn()
            pool_cfg = accessor.get_pool_config()
            await database.init_db_pool(
                dsn,
                min_size=pool_cfg.min_size,
                max_size=pool_cfg.max_size,
                command_timeout=pool_cfg.command_timeout,
                timeout=pool_cfg.timeout,
            )

            # Wait for the Worker to finish initializing the database schema.
            db_manager_for_wait = DatabaseManager()
            await db_manager_for_wait.wait_for_schema_ready(timeout=60)

            app.state.db_manager = DatabaseManager()
            app.state.http_client_factory = HttpClientFactory(accessor)
            app.state.gateway_cache = GatewayCache(accessor, app.state.db_manager)

            await app.state.gateway_cache.populate_caches()

            task = asyncio.create_task(
                _cache_refresh_loop(app.state.gateway_cache, interval_sec=10)
            )
            app.state.cache_refresh_task = task

            # Launch pool health logging background task.
            # Use getattr with a fallback so the lifespan is resilient to
            # HttpClientFactory substitution (e.g. test mocks). A bare
            # MagicMock auto-creates any attribute, so an isinstance guard is
            # required to ensure only real integers enable the health loop.
            factory = app.state.http_client_factory
            interval = getattr(factory, "_pool_health_log_interval_sec", 0)
            if isinstance(interval, int) and interval > 0:
                health_task = asyncio.create_task(
                    _pool_health_log_loop(factory, interval)
                )
                app.state.pool_health_task = health_task

            # Assign the pre-calculated dispatcher state
            app.state.full_stream_instances = full_stream_instances
            app.state.debug_mode_map = debug_mode_map

        except Exception as e:
            logger.critical(
                "A critical error occurred during application startup.", exc_info=e
            )
            raise

        # The 'yield' separates startup from shutdown logic
        yield

        # --- Shutdown Logic ---
        logger.info("Gateway service shutting down...")
        if guard_task is not None:
            guard_task.cancel()
        set_network_guard(None)
        if task := getattr(app.state, "cache_refresh_task", None):
            task.cancel()
        if health_task := getattr(app.state, "pool_health_task", None):
            health_task.cancel()
        if http_factory := getattr(app.state, "http_client_factory", None):
            await http_factory.close_all()
        await database.close_db_pool()
        logger.info("All resources have been released gracefully.")

    app = FastAPI(title="llmGateway - API Gateway Service", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Liveness probe: the process is alive and serving."""
        return JSONResponse(status_code=200, content={"status": "ok"})

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        """Readiness probe: not paused by the network guard."""
        guard = getattr(request.app.state, "network_guard", None)
        if isinstance(guard, NetworkGuard) and guard.enforcing and guard.is_down():
            return JSONResponse(
                status_code=503,
                content={"status": "network_down", "guard": guard.snapshot()},
                headers={"Retry-After": "60"},
            )
        return JSONResponse(status_code=200, content={"status": "ready"})

    @app.get("/metrics")
    async def metrics_endpoint(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        """
        Expose metrics in Prometheus format via auth-proxy to Keeper.

        Validates the Bearer token using ``src.metrics.auth`` domain
        functions and proxies the request to ``http://keeper:9090/metrics``
        inside the Docker network.
        """
        accessor = _get_config_accessor(request)
        try:
            expected_token = validate_metrics_access(accessor)
        except MetricsAuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e

        raw_token = _get_token_from_headers(authorization)
        try:
            validate_metrics_token(raw_token, expected_token)
        except MetricsAuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                keeper_resp = await client.get(
                    "http://keeper:9090/metrics",
                )
                return Response(
                    content=keeper_resp.content,
                    media_type=keeper_resp.headers.get("content-type", "text/plain"),
                )
        except httpx.TransportError:
            raise HTTPException(
                status_code=502, detail="Keeper metrics unavailable"
            ) from None

    _ = metrics_endpoint

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all_endpoint(request: Request) -> Response:
        """
        This endpoint acts as a lean dispatcher. It authenticates the request
        and routes it to the correct specialized handler based on pre-calculated logic.
        """
        token = _get_token_from_headers(
            request.headers.get("authorization"), request.headers.get("x-goog-api-key")
        )
        if not token:
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid authentication token."},
            )

        cache: GatewayCache = request.app.state.gateway_cache
        instance_name = cache.get_instance_name_by_token(token)
        if not instance_name:
            return JSONResponse(
                status_code=401, content={"error": "Invalid authentication token."}
            )

        guard = getattr(request.app.state, "network_guard", None)
        if isinstance(guard, NetworkGuard) and guard.enforcing and guard.is_down():
            return JSONResponse(
                status_code=503,
                content={
                    "error": (
                        "Network outage guard is active: upstream attempts are "
                        "paused. Fix connectivity and restart the container."
                    )
                },
                headers={"Retry-After": "60"},
            )

        try:
            accessor = _get_config_accessor(request)
            provider_config = accessor.get_provider_or_raise(instance_name)
            provider = get_provider(instance_name, provider_config)
        except (KeyError, ValueError) as e:
            logger.error(f"Configuration error for instance '{instance_name}': {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server configuration error."},
            )

        # Get the effective debug mode for this provider
        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )

        # Dispatch to the correct handler based on pre-calculated logic.
        # Debug mode and retry policy force buffered request handling.
        if (
            effective_debug_mode != "disabled"
            or provider_config.gateway_policy.retry.enabled
        ):
            return await _handle_buffered_retryable_request(
                request, provider, instance_name
            )

        # Default: full-stream transparent proxy for all instances.
        return await _handle_full_stream_request(request, provider, instance_name)

    _ = catch_all_endpoint

    return app
