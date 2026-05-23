## Why

Requests through the llmGateway API Gateway can hang silently for up to 20 minutes (4 retries × 300s httpx `read` timeout = 1200s) with zero log entries during the hang. When the upstream connection stalls mid-stream (headers received, body never arrives), the `StreamMonitor` blocks on `aiter_bytes().__anext__()` without producing any log output. No total request lifecycle timeout exists — the `while True` retry loop lacks an `asyncio.timeout()` wrapper. Additionally, network error logs are uninformative (no exception type, URL, or timing data), httpx connection pool limits are unconfigured (no `keepalive_expiry`, no `max_connections` tuning), and fire-and-forget DB tasks (`_report_key_failure`, `cache.remove_key_from_pool`) can block indefinitely without query timeouts.

## What Changes

- **Request lifecycle timeout**: Add `asyncio.timeout()` wrapper around the retry loop in `_handle_buffered_retryable_request()`, controlled by a new `total` field in `TimeoutConfig`. Exhausted timeout returns `504 Gateway Timeout` with structured error body.
- **Enhanced network error logging**: Expand `logger.error()` in `_send_proxy_request()` to include exception type (`ReadTimeout`, `RemoteProtocolError`, etc.), upstream URL, and human-readable detail per error type. Improve retry attempt logs with key ID and HTTP status code.
- **HTTP client connection pool configuration**: New top-level `http_client` config section with `pool` limits (`max_connections`, `max_keepalive_connections`, `keepalive_expiry`) passed to `httpx.Limits`. `HttpClientFactory` reads these globally — applied identically to both Keeper and Gateway.
- **httpx/httpcore logging control**: New `http_client` logging section under `logging` config to control httpx and httpcore log levels independently from the application log level. `httpcore_level: "WARNING"` by default prevents noise; set to `"DEBUG"` for HTTP/2 protocol tracing. `trace_enabled` flag for `extensions={"trace": handler}` per-request.
- **`dedicated_http_client: true` by default**: Change `ProviderConfig.dedicated_http_client` default from `False` to `True`, isolating each provider's connection pool.
- **Database query timeouts**: Add `command_timeout` and `connect_timeout` to `DatabasePoolConfig`, passed to `asyncpg.create_pool()`. Prevents indefinite hangs in fire-and-forget tasks and cache refresh queries.
- **Example config updates**: `example_full_config.yaml` and `example_minimal_config.yaml` updated with new sections and defaults.

## Capabilities

### New Capabilities
- `request-lifecycle-timeout`: Total request deadline enforced via `asyncio.timeout()` around the gateway retry loop, returning 504 on exhaustion. Controlled by `timeouts.total` in `TimeoutConfig`.
- `http-client-pool-config`: Global HTTP connection pool limits (`max_connections`, `max_keepalive_connections`, `keepalive_expiry`) in a new top-level `http_client.pool` config section, applied by `HttpClientFactory`.
- `http-client-logging`: Independent log level control for httpx and httpcore libraries via `logging.http_client` config section, plus optional per-request trace via httpx `extensions`.

### Modified Capabilities
- `transparent-gateway-routing`: The retry loop (`_handle_buffered_retryable_request`) now enforces a total request deadline. The full-stream path (`_handle_full_stream_request`) is unchanged (no retry loop). Error logging in the provider layer now includes structured detail. Timeout exhaustion returns 504 instead of generic 503.

## Impact

- **Config schema** (`src/config/schemas.py`): `TimeoutConfig` gains `total` field; new `HttpClientPoolConfig`, `HttpClientConfig`, `HttpClientLoggingConfig` models; `DatabasePoolConfig` gains `command_timeout`/`connect_timeout`; `ProviderConfig.dedicated_http_client` default changed.
- **Config accessor** (`src/core/accessor.py`): New `get_http_client_config()` method.
- **Logging config** (`src/config/logging_config.py`): New `_setup_http_client_logging()` function.
- **HTTP client factory** (`src/core/http_client_factory.py`): Reads pool config, passes `httpx.Limits` to client creation. Reads trace_enabled flag.
- **Provider base** (`src/providers/base.py`): Enhanced error logging in `_send_proxy_request()` except block.
- **Gateway service** (`src/services/gateway/gateway_service.py`): `asyncio.timeout()` around retry loop, `asyncio.TimeoutError` handler with 504 response, enhanced retry logging.
- **Database** (`src/db/database.py`): `init_db_pool()` accepts `command_timeout`/`connect_timeout`.
- **DB maintainer** (`src/services/db_maintainer.py`): Override `statement_timeout` before `VACUUM ANALYZE`.
- **Example configs**: New sections and updated defaults in `example_full_config.yaml`, `example_minimal_config.yaml`.
- **Test suite**: New tests for request lifecycle timeout, enhanced error logging format, HTTP client pool config, database query timeouts.
