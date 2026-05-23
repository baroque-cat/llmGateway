## ADDED Requirements

### Requirement: Database query timeout via command_timeout
The `DatabasePoolConfig` schema SHALL include `command_timeout` (default 30.0 seconds, gt=0) and `connect_timeout` (default 60.0 seconds, gt=0) fields. `init_db_pool()` SHALL pass these values to `asyncpg.create_pool()`. All queries through the pool SHALL be subject to `command_timeout` unless explicitly overridden.

#### Scenario: Default command_timeout is 30 seconds
- **WHEN** the YAML config omits the `command_timeout` field from `database.pool`
- **THEN** `asyncpg.create_pool()` SHALL be called with `command_timeout=30.0`

#### Scenario: Query exceeding command_timeout raises exception
- **WHEN** a fire-and-forget `_report_key_failure` task executes `UPDATE key_model_status` and the database does not respond within 30 seconds
- **THEN** asyncpg SHALL raise a timeout exception
- **AND** the exception SHALL be caught by the `try/except` in `_report_key_failure` and logged

#### Scenario: VACUUM ANALYZE overrides command_timeout
- **WHEN** `DatabaseMaintainer` runs `VACUUM ANALYZE`
- **THEN** it SHALL execute `SET statement_timeout = 0` on the connection before issuing VACUUM
- **AND** the VACUUM operation SHALL NOT be terminated by the pool-level `command_timeout`

## MODIFIED Requirements

### Requirement: Gateway does not parse request bodies in full-stream path
In full-stream mode, the gateway SHALL NOT call `provider.parse_request_details()` with the request body. The body SHALL be streamed directly to the upstream without intermediate buffering or parsing.

#### Scenario: Full-stream bypasses body parsing
- **WHEN** the gateway dispatches a request to `_handle_full_stream_request()`
- **THEN** the function SHALL NOT read `request.body()` for model extraction purposes
- **AND** the function SHALL NOT call `provider.parse_request_details()` with non-empty content

### Requirement: Full-stream mode is the default for all instances
The gateway SHALL use full-stream request handling (no body buffering, no body parsing) for all provider instances, unless debug mode is enabled or retry is enabled for that instance.

#### Scenario: Standard instance uses full stream
- **WHEN** a provider has `gateway_policy.debug_mode: "disabled"` and `gateway_policy.retry.enabled: false`
- **THEN** the gateway SHALL handle requests via `_handle_full_stream_request()` without buffering the request body

#### Scenario: Debug mode forces buffered handling
- **WHEN** a provider has `gateway_policy.debug_mode: "full_body"` or `"no_content"`
- **THEN** the gateway SHALL handle requests via `_handle_buffered_retryable_request()` to enable debug logging

#### Scenario: Retry mode forces buffered handling
- **WHEN** a provider has `gateway_policy.retry.enabled: true`
- **THEN** the gateway SHALL handle requests via `_handle_buffered_retryable_request()` to enable key rotation on failure
- **AND** the retry loop SHALL enforce the `timeouts.total` deadline via `asyncio.timeout()`
- **AND** timeout exhaustion SHALL return `504 Gateway Timeout` with structured error body

#### Scenario: Network error logged with structured detail
- **WHEN** `_send_proxy_request()` catches any `httpx.RequestError`
- **THEN** the log message SHALL include the exception type name (e.g., `[ReadTimeout]`), provider name, upstream URL, and human-readable detail specific to the error subtype
- **AND** the log message SHALL be emitted at `ERROR` level without requiring `DEBUG` log level

### Requirement: Gateway forwards requests without model validation
The gateway SHALL NOT validate incoming model names against any configured model list. Any model name present in the request body or URL path SHALL be forwarded to the upstream provider without inspection, rejection, or transformation.

#### Scenario: Unknown model forwarded transparently
- **WHEN** a client sends a request with model name `"nonexistent-model-v9"` not present in `default_model` config
- **THEN** the gateway SHALL select a valid API key for the provider instance and forward the request to the upstream
- **AND** the upstream response SHALL be returned to the client unchanged

### Requirement: Gateway passes URL path verbatim to upstream
The gateway SHALL construct the upstream URL by concatenating the provider's `api_base_url` with the incoming request's URL path and query string. No `endpoint_suffix` or model-specific URL rewriting SHALL occur during proxy request handling.

#### Scenario: Compatible-mode path forwarded unchanged
- **WHEN** a client sends a request to `/compatible-mode/v1/chat/completions` on a provider with `api_base_url: "https://dashscope.aliyuncs.com"`
- **THEN** the upstream request SHALL target `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
