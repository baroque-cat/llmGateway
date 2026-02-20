# src/services/gateway_service.py

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

# Import core application components
from src.core.accessor import ConfigAccessor
from src.core.constants import ErrorReason  # Added explicitly for error type checking
from src.core.http_client_factory import HttpClientFactory
from src.core.interfaces import IProvider
from src.core.models import CheckResult
from src.db import database
from src.db.database import DatabaseManager
from src.providers import get_provider
from src.services.gateway_cache import GatewayCache
from src.services.metrics_exporter import MetricsService

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


# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the application's state and dependencies.
# It is populated during the FastAPI startup event.
app_state: dict[str, Any] = {
    "accessor": None,
    "db_manager": None,
    "http_client_factory": None,
    "gateway_cache": None,
    "metrics_service": None,  # Add metrics service to app state
    "cache_refresh_task": None,
    "metrics_update_task": None,  # Add metrics update task to app state
}

# These are headers that control the connection between two nodes (e.g., client and this proxy).
# They MUST NOT be blindly forwarded to the upstream server, as this can cause protocol conflicts.
# Headers are lowercase for case-insensitive comparison.
HOP_BY_HOP_HEADERS: set[str] = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    # Most importantly, Content-Length must be removed for streaming responses,
    # as FastAPI/Starlette will use 'Transfer-Encoding: chunked' instead.
    "content-length",
    # Content-Encoding (e.g., gzip) is also managed by the client, not forwarded.
    "content-encoding",
}

# Maximum size for body content in debug logs (10KB)
MAX_DEBUG_BODY_SIZE = 10 * 1024

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


def _sanitize_body(body: bytes) -> str:
    """
    Sanitizes the request/response body for logging in debug mode.
    Attempts to parse as JSON and redact known sensitive fields.
    Falls back to safe decoding if parsing fails.
    """
    try:
        # First, try to decode as UTF-8
        decoded_str = body.decode("utf-8")
        # Check if it looks like JSON
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
        try:
            chunk = await self.stream_iterator.__anext__()
            return chunk
        except StopAsyncIteration:
            await self._finalize_logging()
            raise
        except Exception as e:
            # Log the error but re-raise it so FastAPI can handle it properly.
            logger.error(f"Error during streaming: {e}")
            await self._finalize_logging()
            raise

    async def _finalize_logging(self):
        """Logs the final transaction summary after the stream is complete or failed."""
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
        await self.upstream_response.aclose()


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
) -> None:
    """
    Logs debug information based on the debug mode setting.

    Args:
        debug_mode: The effective debug mode ("headers_only" or "full_body").
        instance_name: The name of the provider instance.
        request_method: HTTP method of the request.
        request_path: Path of the request.
        request_headers: Headers from the client request.
        request_body: Body content from the client request.
        response_status: HTTP status code from the upstream response.
        response_headers: Headers from the upstream response.
        response_body: Body content from the upstream response.
    """
    # Sanitize headers before logging
    sanitized_request_headers = _sanitize_headers(request_headers)
    sanitized_response_headers = _sanitize_headers(response_headers)

    # Log basic request info
    logger.info(f"Request to {instance_name}: {request_method} {request_path}")
    logger.info(f"Request headers: {sanitized_request_headers}")

    # Log request body if in full_body mode
    if debug_mode == "full_body":
        request_body_preview = request_body[:MAX_DEBUG_BODY_SIZE]
        if len(request_body) > MAX_DEBUG_BODY_SIZE:
            request_body_preview += b"... (truncated)"
        decoded_request_body = _sanitize_body(request_body_preview)
        logger.info(f"Request body: {decoded_request_body}")

    # Log response info
    logger.info(f"Response from {instance_name}: {response_status}")
    logger.info(f"Response headers: {sanitized_response_headers}")

    # Log response body if in full_body mode
    if debug_mode == "full_body":
        response_body_preview = response_body[:MAX_DEBUG_BODY_SIZE]
        if len(response_body) > MAX_DEBUG_BODY_SIZE:
            response_body_preview += b"... (truncated)"
        decoded_response_body = _sanitize_body(response_body_preview)
        logger.info(f"Response body: {decoded_response_body}")


async def _report_key_failure(
    db_manager: DatabaseManager,
    key_id: int,
    provider_name: str,
    model_name: str,
    result: CheckResult,
) -> None:
    """
    A fire-and-forget background task to report a key failure to the database.
    This implements the "fast feedback loop".
    """
    try:
        # The next_check_time here is a placeholder. The KeyProbe's logic will calculate the real one.
        placeholder_next_check = datetime.now(UTC) + timedelta(minutes=1)
        await db_manager.keys.update_status(
            key_id=key_id,
            model_name=model_name,
            provider_name=provider_name,
            result=result,
            next_check_time=placeholder_next_check,
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


async def _metrics_cache_update_loop(
    metrics_service: MetricsService, interval_sec: int
) -> None:
    """
    An infinite loop that periodically updates the metrics cache.
    """
    logger.info(
        f"Starting metrics cache update loop with an interval of {interval_sec} seconds."
    )
    # Perform initial update immediately
    try:
        await metrics_service.update_metrics_cache()
        logger.info("Initial metrics cache update completed.")
    except Exception:
        logger.error("Error during initial metrics cache update.", exc_info=True)

    while True:
        try:
            await asyncio.sleep(interval_sec)
            await metrics_service.update_metrics_cache()
        except asyncio.CancelledError:
            logger.info("Metrics cache update loop is shutting down.")
            break
        except Exception:
            logger.error(
                "An error occurred in the metrics cache update loop.", exc_info=True
            )


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


def _validate_metrics_token(
    authorization: str | None,
    request: Request,
) -> None:
    """
    Validates the Bearer token for accessing the /metrics endpoint.

    Args:
        authorization: The Authorization header value
        request: FastAPI request object to get the accessor

    Raises:
        HTTPException: If the token is missing or invalid
    """
    accessor = _get_config_accessor(request)
    metrics_config = accessor.get_metrics_config()
    if not metrics_config.enabled:
        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = authorization.split(" ", 1)[1]
    if token != metrics_config.access_token:
        raise HTTPException(status_code=403, detail="Invalid metrics access token")


async def _handle_full_stream_request(
    request: Request, provider: IProvider, instance_name: str, model_name: str
) -> Response:
    """
    Handles requests where both request and response can be streamed (full-duplex).
    Does NOT read the request body into memory.
    """
    cache = _get_gateway_cache(request)
    http_factory = _get_http_client_factory(request)
    db_manager = _get_db_manager(request)

    key_info = cache.get_key_from_pool(instance_name, model_name)
    if not key_info:
        logger.warning(
            f"No valid API keys available in pool for '{instance_name}:{model_name}'."
        )
        return JSONResponse(
            status_code=503, content={"error": "No available API keys."}
        )

    key_id, api_key = key_info
    client = await http_factory.get_client_for_provider(instance_name)

    upstream_response, check_result = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request.method,
        headers=dict(request.headers),
        path=request.url.path,
        query_params=str(request.url.query),
        content=request.stream(),
    )

    if check_result.ok:
        # Case 1: Success. Stream the response back to the client using StreamMonitor.
        # Extract client IP for logging
        client_ip = request.client.host if request.client else "unknown"
        stream_monitor = StreamMonitor(
            upstream_response=upstream_response,
            client_ip=client_ip,
            request_method=request.method,
            request_path=str(request.url),
            provider_name=instance_name,
            model_name=model_name,
            check_result=check_result,
        )
        # Filter out hop-by-hop headers from the upstream response.
        filtered_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return StreamingResponse(
            content=stream_monitor,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
            headers=filtered_headers,
        )

    elif check_result.error_reason.is_client_error():
        # Case 2: Client-side error (e.g., 400 Bad Request). The key is not at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to a client-side error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) will NOT be penalized. Forwarding original error to client."
        )
        # Read the error body from the upstream to forward it.
        try:
            response_body = await upstream_response.aread()
        except Exception:
            # Поток закрыт оптимизатором провайдера (StreamClosed)
            response_body = f'{{"error": "Upstream error: {check_result.message or check_result.error_reason.value}"}}'.encode()
        finally:
            await upstream_response.aclose()
        # Filter headers just like in the success case.
        filtered_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=response_body,
            status_code=upstream_response.status_code,
            headers=filtered_headers,
        )

    else:
        # Case 3: Upstream or key-related error. The key is at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to an upstream/key error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) WILL be penalized."
        )

        # --- Гарантированный вывод логов в full_body ---
        try:
            response_body = await upstream_response.aread()
        except Exception:
            response_body = b""
        finally:
            await upstream_response.aclose()

        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )
        if effective_debug_mode != "disabled":
            _log_debug_info(
                debug_mode=effective_debug_mode,
                instance_name=instance_name,
                request_method=request.method,
                request_path=str(request.url),
                request_headers=dict(request.headers),
                request_body=b"",  # We don't have the original request body in full stream mode
                response_status=upstream_response.status_code,
                response_headers=dict(upstream_response.headers),
                response_body=response_body,
            )
        # ------------------------------------------------

        # Report and remove the failed key from the live cache.
        asyncio.create_task(
            _report_key_failure(
                db_manager, key_id, instance_name, model_name, check_result
            )
        )
        asyncio.create_task(
            cache.remove_key_from_pool(instance_name, model_name, key_id)
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": f"Upstream service failed: {check_result.error_reason.value}"
            },
        )


async def _handle_buffered_request(
    request: Request, provider: IProvider, instance_name: str
) -> Response:
    """
    Handles requests where the request body must be buffered but the response can be streamed.
    """
    cache = _get_gateway_cache(request)
    http_factory = _get_http_client_factory(request)
    db_manager = _get_db_manager(request)
    accessor = _get_config_accessor(request)

    provider_config = accessor.get_provider_or_raise(instance_name)

    # Buffer the request body to parse it
    request_body = await request.body()
    try:
        details = await provider.parse_request_details(
            path=request.url.path, content=request_body
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

    if details.model_name not in provider_config.models:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Model '{details.model_name}' is not permitted for this instance."
            },
        )

    key_info = cache.get_key_from_pool(instance_name, details.model_name)
    if not key_info:
        return JSONResponse(
            status_code=503, content={"error": "No available API keys."}
        )

    key_id, api_key = key_info
    client = await http_factory.get_client_for_provider(instance_name)

    upstream_response, check_result = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request.method,
        headers=dict(request.headers),
        path=request.url.path,
        query_params=str(request.url.query),
        content=request_body,
    )

    if check_result.ok:
        # Case 1: Success. Check if debug logging is needed.
        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )

        if effective_debug_mode != "disabled":
            # Read the entire response body for logging
            response_body = await upstream_response.aread()
            await upstream_response.aclose()

            # Log debug information
            _log_debug_info(
                debug_mode=effective_debug_mode,
                instance_name=instance_name,
                request_method=request.method,
                request_path=request.url.path,
                request_headers=dict(request.headers),
                request_body=request_body,
                response_status=upstream_response.status_code,
                response_headers=dict(upstream_response.headers),
                response_body=response_body,
            )

            # Filter out hop-by-hop headers for the final response
            filtered_headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            }

            # Return buffered response (not streaming) since we've read the entire body
            return Response(
                content=response_body,
                status_code=upstream_response.status_code,
                headers=filtered_headers,
            )
        else:
            # Normal streaming response when debug is disabled
            client_ip = request.client.host if request.client else "unknown"
            stream_monitor = StreamMonitor(
                upstream_response=upstream_response,
                client_ip=client_ip,
                request_method=request.method,
                request_path=str(request.url),
                provider_name=instance_name,
                model_name=details.model_name,
                check_result=check_result,
            )
            filtered_headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            }
            return StreamingResponse(
                content=stream_monitor,
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type"),
                headers=filtered_headers,
            )

    elif check_result.error_reason.is_client_error():
        # Case 2: Client-side error (e.g., 400 Bad Request). The key is not at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to a client-side error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) will NOT be penalized. Forwarding original error to client."
        )
        try:
            response_body = await upstream_response.aread()
        except Exception:
            # Поток закрыт оптимизатором провайдера (StreamClosed)
            response_body = f'{{"error": "Upstream error: {check_result.message or check_result.error_reason.value}"}}'.encode()
        finally:
            await upstream_response.aclose()

        # Log debug information for client errors too
        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )
        if effective_debug_mode != "disabled":
            _log_debug_info(
                debug_mode=effective_debug_mode,
                instance_name=instance_name,
                request_method=request.method,
                request_path=request.url.path,
                request_headers=dict(request.headers),
                request_body=request_body,
                response_status=upstream_response.status_code,
                response_headers=dict(upstream_response.headers),
                response_body=response_body,
            )

        filtered_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=response_body,
            status_code=upstream_response.status_code,
            headers=filtered_headers,
        )

    else:
        # Case 3: Upstream or key-related error. The key is at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to an upstream/key error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) WILL be penalized."
        )

        # --- Гарантированный вывод логов в full_body ---
        try:
            response_body = await upstream_response.aread()
        except Exception:
            response_body = b""
        finally:
            await upstream_response.aclose()

        effective_debug_mode = request.app.state.debug_mode_map.get(
            instance_name, "disabled"
        )
        if effective_debug_mode != "disabled":
            _log_debug_info(
                debug_mode=effective_debug_mode,
                instance_name=instance_name,
                request_method=request.method,
                request_path=request.url.path,
                request_headers=dict(request.headers),
                request_body=request_body,
                response_status=upstream_response.status_code,
                response_headers=dict(upstream_response.headers),
                response_body=response_body,
            )
        # ------------------------------------------------

        asyncio.create_task(
            _report_key_failure(
                db_manager, key_id, instance_name, details.model_name, check_result
            )
        )
        asyncio.create_task(
            cache.remove_key_from_pool(instance_name, details.model_name, key_id)
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": f"Upstream service failed: {check_result.error_reason.value}"
            },
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

    request_body = await request.body()
    try:
        details = await provider.parse_request_details(
            path=request.url.path, content=request_body
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

    if details.model_name not in provider_config.models:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Model '{details.model_name}' is not permitted for this instance."
            },
        )

    failed_key_ids: set[int] = set()
    total_attempts = 0
    key_error_attempts = 0
    server_error_attempts = 0
    last_error_response = None

    while True:
        total_attempts += 1
        key_info = cache.get_key_from_pool(
            instance_name, details.model_name, exclude_key_ids=failed_key_ids
        )
        if not key_info:
            return last_error_response or JSONResponse(
                status_code=503,
                content={"error": "No available API keys to handle the request."},
            )

        key_id, api_key = key_info
        client = await http_factory.get_client_for_provider(instance_name)

        upstream_response, check_result = await provider.proxy_request(
            client=client,
            token=api_key,
            method=request.method,
            headers=dict(request.headers),
            path=request.url.path,
            query_params=str(request.url.query),
            content=request_body,
        )

        if check_result.ok:
            # Case 1: Success. Check if debug logging is needed.
            effective_debug_mode = request.app.state.debug_mode_map.get(
                instance_name, "disabled"
            )

            if effective_debug_mode != "disabled":
                # Read the entire response body for logging
                try:
                    response_body = await upstream_response.aread()
                except Exception:
                    # Поток закрыт оптимизатором провайдера (StreamClosed)
                    response_body = f'{{"error": "Upstream error: {check_result.message or check_result.error_reason.value}"}}'.encode()
                finally:
                    await upstream_response.aclose()

                # Log debug information
                _log_debug_info(
                    debug_mode=effective_debug_mode,
                    instance_name=instance_name,
                    request_method=request.method,
                    request_path=request.url.path,
                    request_headers=dict(request.headers),
                    request_body=request_body,
                    response_status=upstream_response.status_code,
                    response_headers=dict(upstream_response.headers),
                    response_body=response_body,
                )

                # Filter out hop-by-hop headers for the final response
                filtered_headers = {
                    key: value
                    for key, value in upstream_response.headers.items()
                    if key.lower() not in HOP_BY_HOP_HEADERS
                }

                # Return buffered response (not streaming) since we've read the entire body
                return Response(
                    content=response_body,
                    status_code=upstream_response.status_code,
                    headers=filtered_headers,
                )
            else:
                # Normal streaming response when debug is disabled
                client_ip = request.client.host if request.client else "unknown"
                stream_monitor = StreamMonitor(
                    upstream_response=upstream_response,
                    client_ip=client_ip,
                    request_method=request.method,
                    request_path=str(request.url),
                    provider_name=instance_name,
                    model_name=details.model_name,
                    check_result=check_result,
                )
                filtered_headers = {
                    key: value
                    for key, value in upstream_response.headers.items()
                    if key.lower() not in HOP_BY_HOP_HEADERS
                }
                return StreamingResponse(
                    content=stream_monitor,
                    status_code=upstream_response.status_code,
                    media_type=upstream_response.headers.get("content-type"),
                    headers=filtered_headers,
                )

        reason = check_result.error_reason
        logger.warning(
            f"Attempt {total_attempts} failed for '{instance_name}'. Reason: [{reason.value}]"
        )
        logger.info(
            f"Retry status - Total attempts: {total_attempts}, Key errors: {key_error_attempts}/{key_error_policy.attempts}, "
            f"Server errors (current key): {server_error_attempts}/{server_error_policy.attempts}"
        )

        if reason.is_client_error():
            # Case 2: Client-side error. Retrying is pointless. Abort the loop.
            logger.error(
                f"Non-retryable client error received: {reason.value}. Aborting retry cycle."
            )
            try:
                response_body = await upstream_response.aread()
            except Exception:
                # Поток закрыт оптимизатором провайдера (StreamClosed)
                response_body = f'{{"error": "Upstream error: {check_result.message or check_result.error_reason.value}"}}'.encode()
            finally:
                await upstream_response.aclose()

            # Log debug information for client errors too
            effective_debug_mode = request.app.state.debug_mode_map.get(
                instance_name, "disabled"
            )
            if effective_debug_mode != "disabled":
                _log_debug_info(
                    debug_mode=effective_debug_mode,
                    instance_name=instance_name,
                    request_method=request.method,
                    request_path=request.url.path,
                    request_headers=dict(request.headers),
                    request_body=request_body,
                    response_status=upstream_response.status_code,
                    response_headers=dict(upstream_response.headers),
                    response_body=response_body,
                )

            filtered_headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            }
            last_error_response = Response(
                content=response_body,
                status_code=upstream_response.status_code,
                headers=filtered_headers,
            )
            break  # Exit the loop immediately

        # Case 3: Key-specific failures OR Overloaded (503).
        # CRITICAL FIX: We explicitly treat ErrorReason.OVERLOADED as a key failure here.
        # Even though 503 is technically a "server" error in standard HTTP, for LLM providers (like Gemini),
        # it typically means the specific key/project is rate-limited or overloaded.
        # Therefore, we must rotate the key (remove current, get new) instead of just waiting.
        if (not reason.is_retryable()) or (reason == ErrorReason.OVERLOADED):
            # Phase 0 fix: Immediate penalty if fatal
            # (Note: reason.is_fatal() is now true for INVALID_KEY, NO_QUOTA etc from previous refactor)

            # Close the upstream connection to prevent connection pool leaks
            await upstream_response.aclose()

            # Add to local blacklist to prevent fetching the same broken key again
            failed_key_ids.add(key_id)

            logger.warning(
                f"Key fault detected (Reason: {reason.value}). "
                f"Marking key_id {key_id} as failed and removing from pool."
            )

            asyncio.create_task(
                _report_key_failure(
                    db_manager, key_id, instance_name, details.model_name, check_result
                )
            )
            asyncio.create_task(
                cache.remove_key_from_pool(instance_name, details.model_name, key_id)
            )

            key_error_attempts += 1
            server_error_attempts = (
                0  # CRITICAL: Reset server error tracking for the next key
            )

            if key_error_attempts < key_error_policy.attempts:
                # NEW LOGIC: Apply backoff for key rotation to prevent "Key Storm"
                # This protects the DB and logic from spinning too fast if all keys are bad
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
                last_error_response = JSONResponse(
                    status_code=503,
                    content={"error": f"Upstream service failed: {reason.value}"},
                )
                break

        # Case 4: True Transient Server Errors (Timeout, Connection Error, etc).
        # These are unrelated to the specific key, so we keep the key and use backoff.
        elif reason.is_retryable():
            # Close the upstream connection to prevent connection pool leaks
            await upstream_response.aclose()

            server_error_attempts += 1
            if server_error_attempts < server_error_policy.attempts:
                delay = server_error_policy.backoff_sec * (
                    server_error_policy.backoff_factor ** (server_error_attempts - 1)
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
                        details.model_name,
                        check_result,
                    )
                )
                asyncio.create_task(
                    cache.remove_key_from_pool(
                        instance_name, details.model_name, key_id
                    )
                )

                # Fall through to Key Rotation logic
                key_error_attempts += 1
                server_error_attempts = (
                    0  # CRITICAL: Reset server attempts for the new key
                )

                if key_error_attempts < key_error_policy.attempts:
                    delay = key_error_policy.backoff_sec * (
                        key_error_policy.backoff_factor ** (key_error_attempts - 1)
                    )
                    logger.info(
                        f"Rotating key after server retry exhaustion... Backoff {delay:.2f}s."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    last_error_response = JSONResponse(
                        status_code=503,
                        content={"error": f"Upstream service failed: {reason.value}"},
                    )
                    break

    return last_error_response or JSONResponse(
        status_code=503, content={"error": "All retry attempts failed."}
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
        try:
            # Store the accessor in the app state for other components to use.
            app.state.accessor = accessor

            # This block implements the requested feature for detailed startup logging.
            logger.info("[Gateway Startup] Analyzing provider streaming modes...")

            # Initialize data structures for the dispatcher logic.
            full_stream_instances: set[str] = set()
            gemini_stream_instances: set[str] = set()
            single_model_map: dict[str, str] = {}
            debug_mode_map: dict[str, str] = {}  # NEW: Track debug mode per provider

            # Iterate through all enabled providers to analyze and log their mode.
            for name, config in accessor.get_enabled_providers().items():
                mode = ""
                reason = ""

                # Determine the effective debug mode for this provider.
                effective_debug_mode = config.gateway_policy.debug_mode

                # Store the effective debug mode for use during request handling.
                debug_mode_map[name] = effective_debug_mode

                # Determine the effective streaming mode for this provider.
                effective_streaming_mode = config.gateway_policy.streaming_mode

                # If debug mode is enabled, force disable streaming regardless of other settings.
                # Debug mode requires buffering the entire request/response for logging.
                if effective_debug_mode != "disabled":
                    mode = "DEBUG MODE"
                    reason = f"Debug mode '{effective_debug_mode}' enabled - forcing buffered requests"
                # If streaming is explicitly disabled, skip all other rules.
                elif effective_streaming_mode == "disabled":
                    mode = "PARTIAL STREAM"
                    reason = "Streaming is explicitly disabled"
                else:
                    # Rule 1 (Highest priority): Retry policy forces partial streaming.
                    if config.gateway_policy.retry.enabled:
                        mode = "PARTIAL STREAM"
                        reason = "Retry policy is enabled"

                    # Rule 2: Single-model instances can be fully streamed.
                    elif len(config.models) == 1:
                        mode = "FULL STREAM"
                        reason = "Single model configured, no parsing needed"
                        # Update state for the dispatcher.
                        full_stream_instances.add(name)
                        single_model_map[name] = list(config.models.keys())[0]

                    # Rule 3: Special case for Gemini's URL-based model selection.
                    elif config.provider_type == "gemini":
                        mode = "FULL STREAM"
                        reason = "Provider type 'gemini' allows model parsing from URL"
                        # Update state for the dispatcher.
                        gemini_stream_instances.add(name)

                    # Rule 4 (Default): Multi-model instances require body parsing.
                    else:
                        mode = "PARTIAL STREAM"
                        reason = "Multiple models require request body parsing"

                # Log the determined mode and reason for operational clarity.
                logger.info(
                    f"[Gateway Startup] - Instance '{name}' -> {mode} (Reason: {reason})"
                )

            logger.info("[Gateway Startup] Analysis complete.")

            dsn = accessor.get_database_dsn()
            await database.init_db_pool(dsn)

            # Wait for the Worker to finish initializing the database schema.
            db_manager_for_wait = DatabaseManager(accessor)
            await db_manager_for_wait.wait_for_schema_ready(timeout=60)

            app.state.db_manager = DatabaseManager(accessor)
            app.state.http_client_factory = HttpClientFactory(accessor)
            app.state.gateway_cache = GatewayCache(accessor, app.state.db_manager)

            await app.state.gateway_cache.populate_caches()

            task = asyncio.create_task(
                _cache_refresh_loop(app.state.gateway_cache, interval_sec=10)
            )
            app.state.cache_refresh_task = task

            # Initialize metrics service if enabled and access token is configured
            metrics_config = accessor.get_metrics_config()
            if metrics_config.enabled and metrics_config.access_token:
                app.state.metrics_service = MetricsService(app.state.db_manager)
                logger.info(
                    "Metrics service initialized and registered with Prometheus client."
                )

                # Start periodic metrics cache update task
                metrics_update_task = asyncio.create_task(
                    _metrics_cache_update_loop(
                        app.state.metrics_service, interval_sec=30
                    )
                )
                app.state.metrics_update_task = metrics_update_task
            else:
                app.state.metrics_service = None
                app.state.metrics_update_task = None
                if metrics_config.enabled and not metrics_config.access_token:
                    logger.warning(
                        "Metrics enabled but no access token configured. Metrics endpoint disabled."
                    )
                else:
                    logger.info("Metrics service is disabled.")

            # Assign the pre-calculated dispatcher state
            app.state.full_stream_instances = full_stream_instances
            app.state.gemini_stream_instances = gemini_stream_instances
            app.state.single_model_map = single_model_map
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
        if task := getattr(app.state, "cache_refresh_task", None):
            task.cancel()
        if metrics_task := getattr(app.state, "metrics_update_task", None):
            metrics_task.cancel()
        if http_factory := getattr(app.state, "http_client_factory", None):
            await http_factory.close_all()
        await database.close_db_pool()
        logger.info("All resources have been released gracefully.")

    app = FastAPI(title="llmGateway - API Gateway Service", lifespan=lifespan)

    @app.get("/metrics")
    async def metrics_endpoint(  # pyright: ignore[reportUnusedFunction]
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        """
        Expose metrics in Prometheus format.
        """
        metrics_service = request.app.state.metrics_service
        if not metrics_service:
            raise HTTPException(
                status_code=404, detail="Metrics endpoint is not enabled"
            )

        _validate_metrics_token(authorization, request)
        metrics_data, content_type = metrics_service.get_metrics()
        return Response(content=metrics_data, media_type=content_type)

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all_endpoint(request: Request) -> Response:  # type: ignore
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
        # Debug mode has highest priority and forces buffered requests.
        if effective_debug_mode != "disabled":
            return await _handle_buffered_request(request, provider, instance_name)
        elif provider_config.gateway_policy.retry.enabled:
            return await _handle_buffered_retryable_request(
                request, provider, instance_name
            )
        elif instance_name in request.app.state.full_stream_instances:
            model_name = request.app.state.single_model_map[instance_name]
            return await _handle_full_stream_request(
                request, provider, instance_name, model_name
            )
        elif instance_name in request.app.state.gemini_stream_instances:
            try:
                # For Gemini, we can parse the model from the URL without reading the body.
                details = await provider.parse_request_details(
                    path=request.url.path, content=b""
                )
                if details.model_name not in provider_config.models:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": f"Model '{details.model_name}' is not permitted."
                        },
                    )
                return await _handle_full_stream_request(
                    request, provider, instance_name, details.model_name
                )
            except ValueError as e:
                return JSONResponse(
                    status_code=400, content={"error": f"Bad request: {e}"}
                )

        # The default case for multi-model, non-Gemini providers: buffer request, stream response.
        return await _handle_buffered_request(request, provider, instance_name)

    return app
