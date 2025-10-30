# src/services/gateway_service.py 

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, AsyncGenerator

from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Send

# Import core application components
from src.core.accessor import ConfigAccessor
from src.core.enums import ErrorReason
from src.core.http_client_factory import HttpClientFactory
from src.core.models import CheckResult, RequestDetails
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

# --- NEW: Universal Streaming Response Generator ---

async def _generate_streaming_response(upstream_response: Response) -> AsyncGenerator[bytes, None]:
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


# --- NEW: Specialized Request Handlers ---

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
    # FIXED: Use attribute access (.key) instead of subscripting (["key"])
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
        content=request.stream()  # Pass the async iterator directly
    )

    if check_result.ok:
        return StreamingResponse(
            content=_generate_streaming_response(upstream_response),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
            headers=dict(upstream_response.headers)
        )
    else:
        logger.warning(f"Request failed for '{instance_name}' in full-stream mode. Reason: {check_result.error_reason.value}")
        # Report and remove the failed key from the live cache.
        asyncio.create_task(
            _report_key_failure(db_manager, key_id, instance_name, model_name, check_result)
        )
        asyncio.create_task(cache.remove_key_from_pool(instance_name, model_name, key_id))
        return JSONResponse(status_code=503, content={"error": f"Upstream service failed: {check_result.error_reason.value}"})


async def _handle_buffered_request(
    request: Request,
    provider: IProvider,
    instance_name: str
) -> Response:
    """
    Handles requests where the request body must be buffered but the response can be streamed.
    """
    # FIXED: Use attribute access (.key) instead of subscripting (["key"])
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

    if check_result.ok:
        return StreamingResponse(
            content=_generate_streaming_response(upstream_response),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
            headers=dict(upstream_response.headers)
        )
    else:
        logger.warning(f"Request failed for '{instance_name}' in buffered mode. Reason: {check_result.error_reason.value}")
        asyncio.create_task(
            _report_key_failure(db_manager, key_id, instance_name, details.model_name, check_result)
        )
        asyncio.create_task(cache.remove_key_from_pool(instance_name, details.model_name, key_id))
        return JSONResponse(status_code=503, content={"error": f"Upstream service failed: {check_result.error_reason.value}"})


async def _handle_buffered_retryable_request(
    request: Request,
    provider: IProvider,
    instance_name: str
) -> Response:
    """
    Handles requests where retry is enabled. Requires buffering the request body.
    Streams the response on the first successful attempt.
    """
    # FIXED: Use attribute access (.key) instead of subscripting (["key"])
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

    while True:
        # Check if we can still retry based on any policy
        can_retry_key_error = key_error_attempts < key_error_policy.attempts
        can_retry_server_error = server_error_attempts < server_error_policy.attempts

        if not can_retry_key_error and not can_retry_server_error:
            logger.error(f"All retry attempts exhausted for request to '{instance_name}'.")
            return last_error_response or JSONResponse(status_code=503, content={"error": "All retry attempts failed."})

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

        if check_result.ok:
            # First successful attempt, stream the response and finish.
            return StreamingResponse(
                content=_generate_streaming_response(upstream_response),
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type"),
                headers=dict(upstream_response.headers)
            )

        reason = check_result.error_reason
        logger.warning(f"Attempt failed for '{instance_name}'. Reason: [{reason.value}], Message: {check_result.message}")
        last_error_response = JSONResponse(status_code=503, content={"error": f"Upstream service failed: {reason.value}"})

        # --- Key Error Logic ---
        if reason in {ErrorReason.INVALID_KEY, ErrorReason.NO_QUOTA, ErrorReason.NO_ACCESS}:
            # Report failure to DB and remove from live cache
            asyncio.create_task(
                _report_key_failure(db_manager, key_id, instance_name, details.model_name, check_result)
            )
            asyncio.create_task(cache.remove_key_from_pool(instance_name, details.model_name, key_id))

            key_error_attempts += 1
            if key_error_attempts < key_error_policy.attempts:
                logger.info(f"Key error detected. Retrying with a new key... (Attempt {key_error_attempts + 1}/{key_error_policy.attempts})")
                continue
            else:
                break # Exhausted key retries

        # --- Server Error Logic ---
        elif reason in {ErrorReason.SERVER_ERROR, ErrorReason.OVERLOADED, ErrorReason.TIMEOUT, ErrorReason.NETWORK_ERROR}:
            server_error_attempts += 1
            if server_error_attempts < server_error_policy.attempts:
                delay = server_error_policy.backoff_sec * (server_error_policy.backoff_factor ** (server_error_attempts -1))
                logger.info(f"Server error detected. Retrying in {delay:.2f}s... (Attempt {server_error_attempts + 1}/{server_error_policy.attempts})")
                await asyncio.sleep(delay)
                continue
            else:
                break # Exhausted server retries

        # --- Non-Retryable Error ---
        else:
            logger.error(f"Non-retryable error received from upstream: {reason.value}. Aborting.")
            break

    return last_error_response


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
            app.state.accessor = accessor

            # Pre-calculate streaming modes for all providers
            logger.info("Pre-calculating streaming modes for providers...")

            # Initialize state containers BEFORE using them
            app.state.full_stream_instances = set()
            app.state.gemini_stream_instances = set()
            app.state.single_model_map = {}
            
            for name, config in accessor.get_enabled_providers().items():
                if config.gateway_policy.retry.enabled:
                    continue # Retry mode disables full streaming
                
                if len(config.models) == 1:
                    app.state.full_stream_instances.add(name)
                    app.state.single_model_map[name] = list(config.models.keys())[0]
                elif config.provider_type == "gemini":
                    app.state.gemini_stream_instances.add(name)
            
            logger.info(f"Found {len(app.state.full_stream_instances)} single-model and "
                        f"{len(app.state.gemini_stream_instances)} Gemini instances eligible for full streaming.")

            # Initialize database pool
            dsn = accessor.get_database_dsn()
            await database.init_db_pool(dsn)
            
            # Create long-lived service components
            app.state.db_manager = DatabaseManager(accessor)
            app.state.http_client_factory = HttpClientFactory(accessor)
            app.state.gateway_cache = GatewayCache(accessor, app.state.db_manager)

            # Populate caches with initial data
            await app.state.gateway_cache.populate_caches()
            
            # Start background cache refresh task
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
        # FIXED: Use attribute access
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
        # 1. Authentication
        token = _get_token_from_headers(
            request.headers.get("authorization"), request.headers.get("x-goog-api-key")
        )
        if not token:
            return JSONResponse(status_code=401, content={"error": "Missing or invalid authentication token."})
        
        # FIXED: Use attribute access (.key) instead of subscripting (["key"])
        cache: GatewayCache = request.app.state.gateway_cache
        instance_name = cache.get_instance_name_by_token(token)
        if not instance_name:
            return JSONResponse(status_code=401, content={"error": "Invalid authentication token."})

        # 2. Get Dependencies
        try:
            # FIXED: Use attribute access (.key) instead of subscripting (["key"])
            accessor: ConfigAccessor = request.app.state.accessor
            provider_config = accessor.get_provider_or_raise(instance_name)
            provider = get_provider(instance_name, provider_config)
        except (KeyError, ValueError) as e:
            logger.error(f"Configuration error for instance '{instance_name}': {e}")
            return JSONResponse(status_code=500, content={"error": "Internal server configuration error."})
        
        # 3. Dispatch to the correct handler
        if provider_config.gateway_policy.retry.enabled:
            return await _handle_buffered_retryable_request(request, provider, instance_name)
        
        # FIXED: Use attribute access (.key) instead of subscripting (["key"])
        if instance_name in request.app.state.full_stream_instances:
            model_name = request.app.state.single_model_map[instance_name]
            return await _handle_full_stream_request(request, provider, instance_name, model_name)
        
        if instance_name in request.app.state.gemini_stream_instances:
            try:
                # Parse model from URL without reading body
                details = await provider.parse_request_details(path=request.url.path, content=b"")
                if details.model_name not in provider_config.models:
                    return JSONResponse(status_code=400, content={"error": f"Model '{details.model_name}' is not permitted."})
                return await _handle_full_stream_request(request, provider, instance_name, details.model_name)
            except ValueError as e:
                return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})

        # Default case: buffered request, streaming response
        return await _handle_buffered_request(request, provider, instance_name)

    return app
