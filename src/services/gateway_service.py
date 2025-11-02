# src/services/gateway_service.py

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, AsyncGenerator, Set

from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse, StreamingResponse

# Import core application components
from src.core.accessor import ConfigAccessor
from src.core.http_client_factory import HttpClientFactory
from src.core.models import CheckResult
from src.core.types import IProvider
from src.db import database
from src.db.database import DatabaseManager
from src.providers import get_provider
from src.services.gateway_cache import GatewayCache

# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the application's state and dependencies.
# It is populated during the FastAPI startup event.
app_state: dict = {
    "accessor": None,
    "db_manager": None,
    "http_client_factory": None,
    "gateway_cache": None,
    "cache_refresh_task": None,
}

# These are headers that control the connection between two nodes (e.g., client and this proxy).
# They MUST NOT be blindly forwarded to the upstream server, as this can cause protocol conflicts.
# Headers are lowercase for case-insensitive comparison.
HOP_BY_HOP_HEADERS: Set[str] = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'transfer-encoding',
    'upgrade',
    # Most importantly, Content-Length must be removed for streaming responses,
    # as FastAPI/Starlette will use 'Transfer-Encoding: chunked' instead.
    'content-length',
    # Content-Encoding (e.g., gzip) is also managed by the client, not forwarded.
    'content-encoding',
}

# --- Helper Functions ---

def _get_token_from_headers(
    authorization: Optional[str] = Header(None),
    x_goog_api_key: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extracts the API token from request headers with a defined priority.
    1. Checks for 'Authorization: Bearer <token>'.
    2. Falls back to 'x-goog-api-key: <token>'.
    """
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return x_goog_api_key

async def _cache_refresh_loop(cache: GatewayCache, interval_sec: int):
    """
    An infinite loop that periodically refreshes the key pool cache.
    """
    logger.info(f"Starting cache refresh loop with an interval of {interval_sec} seconds.")
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await cache.refresh_key_pool()
        except asyncio.CancelledError:
            logger.info("Cache refresh loop is shutting down.")
            break
        except Exception:
            logger.error("An error occurred in the cache refresh loop.", exc_info=True)

async def _report_key_failure(db_manager: DatabaseManager, key_id: int, provider_name: str, model_name: str, result: CheckResult):
    """
    A fire-and-forget background task to report a key failure to the database.
    This implements the "fast feedback loop".
    """
    try:
        # The next_check_time here is a placeholder. The KeyProbe's logic will calculate the real one.
        placeholder_next_check = datetime.now(timezone.utc) + timedelta(minutes=1)
        await db_manager.keys.update_status(
            key_id=key_id,
            model_name=model_name,
            provider_name=provider_name,
            result=result,
            next_check_time=placeholder_next_check
        )
        logger.info(f"Fast feedback: Successfully reported failure for key_id {key_id} to the database.")
    except Exception as e:
        logger.error(f"Fast feedback: Failed to report key failure for key_id {key_id}.", exc_info=e)

# --- Universal Streaming Response Helpers ---

async def _generate_streaming_body(upstream_response: Response) -> AsyncGenerator[bytes, None]:
    """
    An async generator that streams the response body from the upstream service.
    This helper function follows the DRY principle.
    """
    try:
        async for chunk in upstream_response.aiter_bytes():
            yield chunk
    finally:
        # Ensure the upstream connection is closed when the stream finishes or is interrupted.
        await upstream_response.aclose()

def _create_proxied_streaming_response(upstream_response: Response) -> StreamingResponse:
    """
    Creates a properly configured StreamingResponse for proxying.
    It filters out hop-by-hop headers to prevent protocol conflicts.
    """
    # Filter out hop-by-hop headers from the upstream response.
    filtered_headers = {
        key: value for key, value in upstream_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    return StreamingResponse(
        content=_generate_streaming_body(upstream_response),
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type"),
        headers=filtered_headers
    )

# --- Specialized Request Handlers (Refactored) ---

async def _handle_full_stream_request(
    request: Request,
    provider: IProvider,
    instance_name: str,
    model_name: str
) -> Response:
    """
    Handles requests where both request and response can be streamed (full-duplex).
    Does NOT read the request body into memory.
    """
    cache: GatewayCache = request.app.state.gateway_cache
    http_factory: HttpClientFactory = request.app.state.http_client_factory
    db_manager: DatabaseManager = request.app.state.db_manager

    key_info = cache.get_key_from_pool(instance_name, model_name)
    if not key_info:
        logger.warning(f"No valid API keys available in pool for '{instance_name}:{model_name}'.")
        return JSONResponse(status_code=503, content={"error": "No available API keys."})

    key_id, api_key = key_info
    client = await http_factory.get_client_for_provider(instance_name)

    upstream_response, check_result = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request.method,
        headers=dict(request.headers),
        path=request.url.path,
        query_params=str(request.url.query),
        content=request.stream()
    )

    # --- MODIFIED BLOCK START: Implemented the new 3-way logic ---
    if check_result.ok:
        # Case 1: Success. Stream the response back to the client.
        return _create_proxied_streaming_response(upstream_response)
    
    elif check_result.error_reason.is_client_error():
        # Case 2: Client-side error (e.g., 400 Bad Request). The key is not at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to a client-side error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) will NOT be penalized. Forwarding original error to client."
        )
        # Read the error body from the upstream to forward it.
        response_body = await upstream_response.aread()
        await upstream_response.aclose()
        # Filter headers just like in the success case.
        filtered_headers = {
            key: value for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=response_body,
            status_code=upstream_response.status_code,
            headers=filtered_headers
        )

    else:
        # Case 3: Upstream or key-related error. The key is at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to an upstream/key error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) WILL be penalized."
        )
        # Report and remove the failed key from the live cache.
        asyncio.create_task(
            _report_key_failure(db_manager, key_id, instance_name, model_name, check_result)
        )
        asyncio.create_task(cache.remove_key_from_pool(instance_name, model_name, key_id))
        return JSONResponse(status_code=503, content={"error": f"Upstream service failed: {check_result.error_reason.value}"})
    # --- MODIFIED BLOCK END ---


async def _handle_buffered_request(
    request: Request,
    provider: IProvider,
    instance_name: str
) -> Response:
    """
    Handles requests where the request body must be buffered but the response can be streamed.
    """
    cache: GatewayCache = request.app.state.gateway_cache
    http_factory: HttpClientFactory = request.app.state.http_client_factory
    db_manager: DatabaseManager = request.app.state.db_manager
    accessor: ConfigAccessor = request.app.state.accessor
    
    provider_config = accessor.get_provider_or_raise(instance_name)

    # Buffer the request body to parse it
    request_body = await request.body()
    try:
        details = await provider.parse_request_details(path=request.url.path, content=request_body)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})
    
    if details.model_name not in provider_config.models:
        return JSONResponse(status_code=400, content={"error": f"Model '{details.model_name}' is not permitted for this instance."})

    key_info = cache.get_key_from_pool(instance_name, details.model_name)
    if not key_info:
        return JSONResponse(status_code=503, content={"error": "No available API keys."})

    key_id, api_key = key_info
    client = await http_factory.get_client_for_provider(instance_name)

    upstream_response, check_result = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request.method,
        headers=dict(request.headers),
        path=request.url.path,
        query_params=str(request.url.query),
        content=request_body
    )

    # --- MODIFIED BLOCK START: Implemented the new 3-way logic ---
    if check_result.ok:
        # Case 1: Success. Stream the response back to the client.
        return _create_proxied_streaming_response(upstream_response)

    elif check_result.error_reason.is_client_error():
        # Case 2: Client-side error (e.g., 400 Bad Request). The key is not at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to a client-side error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) will NOT be penalized. Forwarding original error to client."
        )
        response_body = await upstream_response.aread()
        await upstream_response.aclose()
        filtered_headers = {
            key: value for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=response_body,
            status_code=upstream_response.status_code,
            headers=filtered_headers
        )
        
    else:
        # Case 3: Upstream or key-related error. The key is at fault.
        logger.warning(
            f"Request for '{instance_name}' failed due to an upstream/key error: [{check_result.error_reason.value}]. "
            f"The API key (ID: {key_id}) WILL be penalized."
        )
        asyncio.create_task(
            _report_key_failure(db_manager, key_id, instance_name, details.model_name, check_result)
        )
        asyncio.create_task(cache.remove_key_from_pool(instance_name, details.model_name, key_id))
        return JSONResponse(status_code=503, content={"error": f"Upstream service failed: {check_result.error_reason.value}"})
    # --- MODIFIED BLOCK END ---


async def _handle_buffered_retryable_request(
    request: Request,
    provider: IProvider,
    instance_name: str
) -> Response:
    """
    Handles requests where retry is enabled. Requires buffering the request body.
    Streams the response on the first successful attempt.
    """
    cache: GatewayCache = request.app.state.gateway_cache
    http_factory: HttpClientFactory = request.app.state.http_client_factory
    db_manager: DatabaseManager = request.app.state.db_manager
    accessor: ConfigAccessor = request.app.state.accessor

    provider_config = accessor.get_provider_or_raise(instance_name)
    retry_policy = provider_config.gateway_policy.retry
    key_error_policy = retry_policy.on_key_error
    server_error_policy = retry_policy.on_server_error

    request_body = await request.body()
    try:
        details = await provider.parse_request_details(path=request.url.path, content=request_body)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

    if details.model_name not in provider_config.models:
        return JSONResponse(status_code=400, content={"error": f"Model '{details.model_name}' is not permitted for this instance."})

    key_error_attempts = 0
    server_error_attempts = 0
    last_error_response = None

    max_total_attempts = key_error_policy.attempts + server_error_policy.attempts
    
    for attempt in range(max_total_attempts):
        key_info = cache.get_key_from_pool(instance_name, details.model_name)
        if not key_info:
            return JSONResponse(status_code=503, content={"error": "No available API keys to handle the request."})

        key_id, api_key = key_info
        client = await http_factory.get_client_for_provider(instance_name)

        upstream_response, check_result = await provider.proxy_request(
            client=client, token=api_key, method=request.method,
            headers=dict(request.headers), path=request.url.path,
            query_params=str(request.url.query), content=request_body
        )

        # --- MODIFIED BLOCK START: Implemented the new 3-way logic inside the retry loop ---
        if check_result.ok:
            # Case 1: Success. Stream the response and terminate the loop.
            return _create_proxied_streaming_response(upstream_response)

        reason = check_result.error_reason
        logger.warning(f"Attempt {attempt + 1}/{max_total_attempts} failed for '{instance_name}'. Reason: [{reason.value}]")

        if reason.is_client_error():
            # Case 2: Client-side error. Retrying is pointless. Abort the loop.
            logger.error(f"Non-retryable client error received: {reason.value}. Aborting retry cycle.")
            response_body = await upstream_response.aread()
            await upstream_response.aclose()
            filtered_headers = {
                key: value for key, value in upstream_response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            }
            last_error_response = Response(
                content=response_body,
                status_code=upstream_response.status_code,
                headers=filtered_headers
            )
            break # Exit the loop immediately

        # Case 3: Upstream or key-related error. Proceed with retry logic.
        last_error_response = JSONResponse(status_code=503, content={"error": f"Upstream service failed: {reason.value}"})
        
        # --- Key Error Logic ---
        if not reason.is_retryable():
            asyncio.create_task(
                _report_key_failure(db_manager, key_id, instance_name, details.model_name, check_result)
            )
            asyncio.create_task(cache.remove_key_from_pool(instance_name, details.model_name, key_id))

            key_error_attempts += 1
            if key_error_attempts < key_error_policy.attempts:
                logger.info(f"Key error detected. Retrying with a new key... (Key Error Attempt {key_error_attempts}/{key_error_policy.attempts})")
                continue
            else:
                logger.error(f"Exhausted all {key_error_policy.attempts} retry attempts for key errors.")
                break

        # --- Server Error Logic ---
        elif reason.is_retryable():
            server_error_attempts += 1
            if server_error_attempts < server_error_policy.attempts:
                delay = server_error_policy.backoff_sec * (server_error_policy.backoff_factor ** (server_error_attempts -1))
                logger.info(f"Server error detected. Retrying in {delay:.2f}s... (Server Error Attempt {server_error_attempts}/{server_error_policy.attempts})")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"Exhausted all {server_error_policy.attempts} retry attempts for server errors.")
                break
        # --- MODIFIED BLOCK END ---

    return last_error_response or JSONResponse(status_code=503, content={"error": "All retry attempts failed."})


# --- FastAPI Application Factory and Event Handlers ---

def create_app(accessor: ConfigAccessor) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    """
    app = FastAPI(title="llmGateway - API Gateway Service")

    @app.on_event("startup")
    async def startup_event():
        """
        Application startup logic: initialize DB, HTTP clients, caches, and background tasks.
        """
        logger.info("Gateway service starting up...")
        try:
            # Store the accessor in the app state for other components to use.
            app.state.accessor = accessor

            # This block implements the requested feature for detailed startup logging.
            logger.info("[Gateway Startup] Analyzing provider streaming modes...")
            
            # Initialize data structures for the dispatcher logic.
            app.state.full_stream_instances = set()
            app.state.gemini_stream_instances = set()
            app.state.single_model_map = {}
            
            # Iterate through all enabled providers to analyze and log their mode.
            for name, config in accessor.get_enabled_providers().items():
                mode = ""
                reason = ""
                
                # Rule 1 (Highest priority): Retry policy forces partial streaming.
                if config.gateway_policy.retry.enabled:
                    mode = "PARTIAL STREAM"
                    reason = "Retry policy is enabled"
                
                # Rule 2: Single-model instances can be fully streamed.
                elif len(config.models) == 1:
                    mode = "FULL STREAM"
                    reason = "Single model configured, no parsing needed"
                    # Update state for the dispatcher.
                    app.state.full_stream_instances.add(name)
                    app.state.single_model_map[name] = list(config.models.keys())[0]

                # Rule 3: Special case for Gemini's URL-based model selection.
                elif config.provider_type == "gemini":
                    mode = "FULL STREAM"
                    reason = "Provider type 'gemini' allows model parsing from URL"
                    # Update state for the dispatcher.
                    app.state.gemini_stream_instances.add(name)

                # Rule 4 (Default): Multi-model instances require body parsing.
                else:
                    mode = "PARTIAL STREAM"
                    reason = "Multiple models require request body parsing"
                
                # Log the determined mode and reason for operational clarity.
                logger.info(f"[Gateway Startup] - Instance '{name}' -> {mode} (Reason: {reason})")
            
            logger.info("[Gateway Startup] Analysis complete.")

            dsn = accessor.get_database_dsn()
            await database.init_db_pool(dsn)
            
            app.state.db_manager = DatabaseManager(accessor)
            app.state.http_client_factory = HttpClientFactory(accessor)
            app.state.gateway_cache = GatewayCache(accessor, app.state.db_manager)

            await app.state.gateway_cache.populate_caches()
            
            task = asyncio.create_task(
                _cache_refresh_loop(app.state.gateway_cache, interval_sec=10)
            )
            app.state.cache_refresh_task = task
            
        except Exception as e:
            logger.critical("A critical error occurred during application startup.", exc_info=e)
            raise

    @app.on_event("shutdown")
    async def shutdown_event():
        """
        Application shutdown logic: gracefully close all resources.
        """
        logger.info("Gateway service shutting down...")
        if task := getattr(app.state, "cache_refresh_task", None):
            task.cancel()
        if http_factory := getattr(app.state, "http_client_factory", None):
            await http_factory.close_all()
        await database.close_db_pool()
        logger.info("All resources have been released gracefully.")

    # --- The Core Catch-All Endpoint (Dispatcher) ---
    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all_endpoint(request: Request):
        """
        This endpoint acts as a lean dispatcher. It authenticates the request
        and routes it to the correct specialized handler based on pre-calculated logic.
        """
        token = _get_token_from_headers(
            request.headers.get("authorization"), request.headers.get("x-goog-api-key")
        )
        if not token:
            return JSONResponse(status_code=401, content={"error": "Missing or invalid authentication token."})
        
        cache: GatewayCache = request.app.state.gateway_cache
        instance_name = cache.get_instance_name_by_token(token)
        if not instance_name:
            return JSONResponse(status_code=401, content={"error": "Invalid authentication token."})

        try:
            accessor: ConfigAccessor = request.app.state.accessor
            provider_config = accessor.get_provider_or_raise(instance_name)
            provider = get_provider(instance_name, provider_config)
        except (KeyError, ValueError) as e:
            logger.error(f"Configuration error for instance '{instance_name}': {e}")
            return JSONResponse(status_code=500, content={"error": "Internal server configuration error."})
        
        # Dispatch to the correct handler based on pre-calculated logic.
        if provider_config.gateway_policy.retry.enabled:
            return await _handle_buffered_retryable_request(request, provider, instance_name)
        
        if instance_name in request.app.state.full_stream_instances:
            model_name = request.app.state.single_model_map[instance_name]
            return await _handle_full_stream_request(request, provider, instance_name, model_name)
        
        if instance_name in request.app.state.gemini_stream_instances:
            try:
                # For Gemini, we can parse the model from the URL without reading the body.
                details = await provider.parse_request_details(path=request.url.path, content=b"")
                if details.model_name not in provider_config.models:
                    return JSONResponse(status_code=400, content={"error": f"Model '{details.model_name}' is not permitted."})
                return await _handle_full_stream_request(request, provider, instance_name, details.model_name)
            except ValueError as e:
                return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

        # The default case for multi-model, non-Gemini providers: buffer request, stream response.
        return await _handle_buffered_request(request, provider, instance_name)

    return app
