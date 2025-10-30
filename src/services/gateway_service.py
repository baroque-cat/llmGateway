# src/services/gateway_service.py

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse

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
    "cache_refresh_task": None
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
        await asyncio.sleep(interval_sec)
        await cache.refresh_key_pool()

async def _report_key_failure(db_manager: DatabaseManager, key_id: int, provider_name: str, model_name: str, result: CheckResult):
    """
    A fire-and-forget background task to report a key failure to the database.
    This implements the "fast feedback loop".
    """
    try:
        # The next_check_time here is a placeholder; the KeyProbe's calculation is the source of truth.
        # We just need to update the status immediately.
        placeholder_next_check = datetime.utcnow() + timedelta(minutes=1)
        
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

# --- REFACTORED AND TEMPORARILY MODIFIED Request Handlers ---

# JUSTIFICATION FOR CHANGE (as per plan step 2):
# Renamed from _handle_streaming_request to _handle_direct_request because it no longer streams.
# This improves code clarity and reflects its actual (temporary) behavior.
async def _handle_direct_request(
    # JUSTIFICATION FOR CHANGE (as per plan step 1):
    # The signature is changed from `request: Request` to `content: bytes`.
    # This decouples the handler from the FastAPI request object and solves the "body can be read only once" issue.
    content: bytes,
    request_meta: Request, # Keep original request for metadata like method, path, headers
    provider: IProvider,
    instance_name: str,
    model_name: str
) -> Response:
    """
    Handles requests where retry is disabled.
    TEMPORARY DEBUGGING CHANGE: This function now reads the full response body
    into memory and returns a standard `Response`, disabling streaming.
    """
    cache: GatewayCache = app_state["gateway_cache"]
    http_factory: HttpClientFactory = app_state["http_client_factory"]

    key_info = cache.get_key_from_pool(instance_name, model_name)
    if not key_info:
        logger.warning(f"No valid API keys available in pool for '{instance_name}:{model_name}'.")
        return JSONResponse(status_code=503, content={"error": "No available API keys."})
    
    key_id, api_key = key_info

    client = await http_factory.get_client_for_provider(instance_name)
    
    upstream_response, check_result = await provider.proxy_request(
        client=client,
        token=api_key,
        method=request_meta.method,
        headers=dict(request_meta.headers),
        path=request_meta.url.path,
        query_params=str(request_meta.url.query),
        content=content
    )
    
    if check_result.ok:
        # JUSTIFICATION FOR CHANGE (as per plan step 1):
        # This is the core of the "no-streaming" temporary fix.
        # Instead of returning a StreamingResponse, we read the entire body with .aread()
        # and then return a regular fastapi.Response.
        response_body = await upstream_response.aread()
        await upstream_response.aclose()
        return Response(
            content=response_body,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
            headers=dict(upstream_response.headers)
        )
    else:
        logger.warning(f"Request failed for '{instance_name}' in direct mode. Reason: {check_result.error_reason.value}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Upstream service failed: {check_result.error_reason.value}"}
        )

async def _handle_retryable_request(
    # JUSTIFICATION FOR CHANGE (as per plan step 1):
    # Signature changed to accept `content: bytes` for the same reasons as _handle_direct_request.
    content: bytes,
    request_meta: Request,
    provider: IProvider,
    instance_name: str,
    details: RequestDetails,
) -> Response:
    """
    Handles requests where retry is enabled.
    TEMPORARY DEBUGGING CHANGE: This function now reads the full response body
    into memory and returns a standard `Response`, disabling streaming.
    """
    cache: GatewayCache = app_state["gateway_cache"]
    http_factory: HttpClientFactory = app_state["http_client_factory"]
    db_manager: DatabaseManager = app_state["db_manager"]
    accessor: ConfigAccessor = app_state["accessor"]
    
    retry_policy = accessor.get_provider_or_raise(instance_name).gateway_policy.retry
    key_error_policy = retry_policy.on_key_error
    server_error_policy = retry_policy.on_server_error

    key_error_attempts = 0
    server_error_attempts = 0
    last_error_response = None

    while True:
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
            client=client, token=api_key, method=request_meta.method,
            headers=dict(request_meta.headers), path=request_meta.url.path,
            query_params=str(request_meta.url.query), content=content
        )

        if check_result.ok:
            # JUSTIFICATION FOR CHANGE (as per plan step 1):
            # Same as in the other handler, we disable streaming by reading the full body
            # before returning the response.
            response_body = await upstream_response.aread()
            await upstream_response.aclose()
            return Response(
                content=response_body,
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type"),
                headers=dict(upstream_response.headers)
            )

        reason = check_result.error_reason
        logger.warning(
            f"Attempt failed for '{instance_name}'. Reason: [{reason.value}], Message: {check_result.message}"
        )
        last_error_response = JSONResponse(status_code=503, content={"error": f"Upstream service failed: {reason.value}"})

        if reason in {ErrorReason.INVALID_KEY, ErrorReason.NO_QUOTA, ErrorReason.NO_ACCESS}:
            asyncio.create_task(
                _report_key_failure(db_manager, key_id, instance_name, details.model_name, check_result)
            )
            key_error_attempts += 1
            if key_error_attempts < key_error_policy.attempts:
                logger.info(f"Key error detected. Retrying... (Attempt {key_error_attempts + 1}/{key_error_policy.attempts})")
                continue
            else:
                break

        elif reason in {ErrorReason.SERVER_ERROR, ErrorReason.OVERLOADED, ErrorReason.TIMEOUT, ErrorReason.NETWORK_ERROR}:
            server_error_attempts += 1
            if server_error_attempts < server_error_policy.attempts:
                delay = server_error_policy.backoff_sec * (server_error_policy.backoff_factor ** server_error_attempts)
                logger.info(
                    f"Server error detected. Retrying in {delay:.2f}s... "
                    f"(Attempt {server_error_attempts + 1}/{server_error_policy.attempts})"
                )
                await asyncio.sleep(delay)
                continue
            else:
                break
        
        else:
            logger.error(f"Non-retryable error received from upstream: {reason.value}. Aborting.")
            break
    
    return last_error_response


# --- FastAPI Application Factory and Event Handlers ---

def create_app(accessor: ConfigAccessor) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    It now only takes an accessor and manages its own dependencies.
    """
    app = FastAPI(title="llmGateway - API Gateway Service")

    app_state["accessor"] = accessor

    @app.on_event("startup")
    async def startup_event():
        logger.info("Gateway service starting up...")
        
        try:
            accessor: ConfigAccessor = app_state["accessor"]
            
            dsn = accessor.get_database_dsn()
            await database.init_db_pool(dsn)
            logger.info("Database connection pool initialized successfully.")
            
            logger.info("Creating service components (DB Manager, HTTP Factory, Cache)...")
            db_manager = DatabaseManager(accessor)
            http_client_factory = HttpClientFactory(accessor)
            gateway_cache = GatewayCache(accessor, db_manager)
            
            app_state["db_manager"] = db_manager
            app_state["http_client_factory"] = http_client_factory
            app_state["gateway_cache"] = gateway_cache
            logger.info("Service components created and stored in app state.")

            await gateway_cache.populate_caches()
            
            worker_config = accessor.get_worker_config()
            task = asyncio.create_task(
                _cache_refresh_loop(gateway_cache, interval_sec=30)
            )
            app_state["cache_refresh_task"] = task
            logger.info("Background cache refresh task has been started.")

        except Exception as e:
            logger.critical("A critical error occurred during application startup.", exc_info=e)
            raise

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Gateway service shutting down...")
        task = app_state.get("cache_refresh_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("Background cache refresh task successfully cancelled.")
        
        http_client_factory = app_state.get("http_client_factory")
        if http_client_factory:
            await http_client_factory.close_all()
        
        await database.close_db_pool()
        logger.info("All resources (HTTP clients, DB pool) have been released gracefully.")

    # --- The Core Catch-All Endpoint ---
    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all_endpoint(
        request: Request,
        full_path: str,
        authorization: Optional[str] = Header(None),
        x_goog_api_key: Optional[str] = Header(None)
    ):
        # --- 1. Fast Authentication (from cache) ---
        token = _get_token_from_headers(authorization, x_goog_api_key)
        if not token:
            return JSONResponse(status_code=401, content={"error": "Missing or invalid authentication token."})
        
        instance_name = app_state["gateway_cache"].get_instance_name_by_token(token)
        if not instance_name:
            return JSONResponse(status_code=401, content={"error": "Invalid authentication token."})

        # --- 2. Get Dependencies ---
        try:
            accessor: ConfigAccessor = app_state["accessor"]
            provider_config = accessor.get_provider_or_raise(instance_name)
            provider = get_provider(instance_name, provider_config)
        except (KeyError, ValueError) as e:
            logger.error(f"Configuration error for instance '{instance_name}': {e}")
            return JSONResponse(status_code=500, content={"error": "Internal server configuration error."})
        
        # --- 3. Parse Request and Decide Logic Path ---
        
        # JUSTIFICATION FOR CHANGE (as per plan step 3):
        # This is the core logic change. We implement the conditional workflow
        # to handle different provider types correctly.
        
        details: RequestDetails
        request_body: bytes
        
        if provider_config.provider_type == "gemini":
            # For Gemini, parse details from the path first, without touching the body.
            try:
                details = await provider.parse_request_details(path=full_path, content=b"")
            except ValueError as e:
                return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})
            
            # Now that we know the model and are ready to proxy, we can safely read the body.
            request_body = await request.body()
        
        else: # For 'openai_like', 'deepseek', etc.
            # For these providers, we MUST read the body to determine the model.
            request_body = await request.body()
            try:
                details = await provider.parse_request_details(path=full_path, content=request_body)
            except ValueError as e:
                return JSONResponse(status_code=400, content={"error": f"Bad request: {e}"})
        
        if details.model_name not in provider_config.models:
            return JSONResponse(
                status_code=400,
                content={"error": f"Model '{details.model_name}' is not permitted for this provider instance."}
            )

        # JUSTIFICATION FOR CHANGE (as per plan step 3):
        # The 'synthetic_request' workaround is now removed. It's no longer needed because
        # we pass the `request_body` (bytes) directly to the handlers.
        
        retry_policy = provider_config.gateway_policy.retry
        if retry_policy.enabled:
            return await _handle_retryable_request(request_body, request, provider, instance_name, details)
        else:
            # Call the renamed function
            return await _handle_direct_request(request_body, request, provider, instance_name, details.model_name)

    return app

