# transparent-gateway-routing

## Purpose

Defines the behavior of the Conductor (API Gateway) as a fully transparent proxy.
The gateway forwards requests to upstream providers without model validation,
per-model key selection, or request body parsing in the hot path. Full-stream
mode is the default; only debug and retry modes trigger buffered handling.

## Requirements

### Requirement: Gateway forwards requests without model validation
The gateway SHALL NOT validate incoming model names against any configured model list. Any model name present in the request body or URL path SHALL be forwarded to the upstream provider without inspection, rejection, or transformation.

#### Scenario: Unknown model forwarded transparently
- **WHEN** a client sends a request with model name `"nonexistent-model-v9"` not present in `default_model` config
- **THEN** the gateway SHALL select a valid API key for the provider instance and forward the request to the upstream
- **AND** the upstream response SHALL be returned to the client unchanged

#### Scenario: Model validation code removed
- **WHEN** the gateway processes any incoming request in the hot path
- **THEN** no code path SHALL execute `if details.model_name not in provider_config.default_model` or equivalent model membership checks

### Requirement: Gateway passes URL path verbatim to upstream
The gateway SHALL construct the upstream URL by concatenating the provider's `api_base_url` with the incoming request's URL path and query string. No `endpoint_suffix` or model-specific URL rewriting SHALL occur during proxy request handling.

#### Scenario: Compatible-mode path forwarded unchanged
- **WHEN** a client sends a request to `/compatible-mode/v1/chat/completions` on a provider with `api_base_url: "https://dashscope.aliyuncs.com"`
- **THEN** the upstream request SHALL target `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- **AND** the request body SHALL be forwarded without modification

#### Scenario: Compatible-api path forwarded unchanged
- **WHEN** a client sends a request to `/compatible-api/v1/reranks` on the same provider
- **THEN** the upstream request SHALL target `https://dashscope.aliyuncs.com/compatible-api/v1/reranks`

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
- **AND** timeout exhaustion SHALL return `504 Gateway Timeout` with structured error body `{"error": "...", "attempts": <int>, "last_error": "<reason>"}`

#### Scenario: Network error logged with structured detail
- **WHEN** `_send_proxy_request()` catches any `httpx.RequestError`
- **THEN** the log message SHALL include the exception type name (e.g., `[ReadTimeout]`), provider name, upstream URL, and human-readable detail specific to the error subtype
- **AND** the log message SHALL be emitted at `ERROR` level without requiring `DEBUG` log level

### Requirement: Gateway does not parse request bodies in full-stream path
In full-stream mode, the gateway SHALL NOT call `provider.parse_request_details()` with the request body. The body SHALL be streamed directly to the upstream without intermediate buffering or parsing.

#### Scenario: Full-stream bypasses body parsing
- **WHEN** the gateway dispatches a request to `_handle_full_stream_request()`
- **THEN** the function SHALL NOT read `request.body()` for model extraction purposes
- **AND** the function SHALL NOT call `provider.parse_request_details()` with non-empty content

### Requirement: Gemini URL-based model parsing is preserved for logging
For Gemini provider instances in full-stream mode, `provider.parse_request_details()` MAY be called with an empty body (`b""`) to extract the model name from the URL path for logging purposes. This SHALL NOT affect routing or key selection decisions.

#### Scenario: Gemini full-stream extracts model from URL for logs
- **WHEN** a Gemini provider receives a request to `/v1beta/models/gemini-2.5-pro:generateContent` in full-stream mode
- **THEN** `parse_request_details(path=request.url.path, content=b"")` MAY be called
- **AND** the extracted model name `"gemini-2.5-pro"` MAY be used in log messages
- **AND** the model name SHALL NOT be used for key selection or request validation

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

### Requirement: Both request paths honor the configured key selection mode
The gateway dispatcher and both request handlers (`_handle_full_stream_request()` and `_handle_buffered_retryable_request()`) SHALL obtain keys through the selection mechanism configured for the provider instance (`round_robin` default or `sticky`). The dispatch decision between full-stream and buffered handling SHALL NOT change based on the selection mode.

#### Scenario: Sticky mode in full-stream path
- **WHEN** a provider has sticky mode with `retry.enabled: false` and `debug_mode: disabled`
- **THEN** the request SHALL be dispatched to `_handle_full_stream_request()`
- **AND** the key SHALL be obtained via sticky selection

#### Scenario: Sticky mode in buffered path
- **WHEN** a provider has sticky mode with `retry.enabled: true`
- **THEN** the request SHALL be dispatched to `_handle_buffered_retryable_request()`
- **AND** the key SHALL be obtained via sticky selection

#### Scenario: Dispatch unchanged by selection mode
- **WHEN** a provider switches between `round_robin` and `sticky` modes with all other settings equal
- **THEN** the choice between full-stream and buffered handling SHALL remain determined solely by `debug_mode` and `retry.enabled`

### Requirement: Sticky retry semantics in the buffered path
In sticky mode, the retry loop in `_handle_buffered_retryable_request()` SHALL retry the REQUEST with a NEW key on every rotation trigger (fatal errors, `OVERLOADED`, `RATE_LIMITED`, and server errors per `is_server_error()`). The same-key retry branch driven by `on_server_error` SHALL NOT execute in sticky mode, and `on_server_error` settings SHALL be ignored. Key-rotation attempts SHALL be governed by `on_key_error` (`attempts`, `backoff_sec`, `backoff_factor`). The `asyncio.timeout(timeouts.total)` deadline SHALL continue to wrap the loop, and timeout exhaustion SHALL return `504 Gateway Timeout` with the structured error body defined by the retry-mode requirement.

#### Scenario: Retryable error consumes key-error attempts in sticky mode
- **WHEN** a sticky retry-loop request fails with `ErrorReason.NETWORK_ERROR` and `on_key_error.attempts` is 3
- **THEN** the failed key SHALL be excluded and `key_error_attempts` SHALL increment
- **AND** the request SHALL be retried with a new key after the `on_key_error` backoff
- **AND** the `on_server_error` attempt counter SHALL NOT be used

#### Scenario: Total deadline still enforced in sticky mode
- **WHEN** the sticky retry loop exceeds `timeouts.total`
- **THEN** the gateway SHALL return `504 Gateway Timeout` with the structured error body `{"error": "...", "attempts": <int>, "last_error": "<reason>"}`

### Requirement: Server errors do not penalize keys in sticky mode
In sticky mode, when a request fails with a reason where `is_server_error()` is true (`SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT`), neither request handler SHALL call `_report_key_failure` nor `remove_key_from_pool` for the failed key, regardless of retry being enabled. This applies in addition to, and does not modify, the `pool-error-isolation` behavior for client errors. Round-robin mode SHALL keep the existing penalty behavior unchanged.

#### Scenario: Server error in sticky full-stream path leaves key untouched
- **WHEN** a full-stream request in sticky mode fails with `ErrorReason.SERVER_ERROR`
- **THEN** `_report_key_failure` SHALL NOT be called
- **AND** `remove_key_from_pool` SHALL NOT be called
- **AND** the sticky pointer SHALL rotate to a different key for subsequent requests

#### Scenario: Round-robin penalty behavior unchanged
- **WHEN** a request in round-robin mode fails with `ErrorReason.SERVER_ERROR`
- **THEN** the gateway SHALL apply the same penalty behavior as before this change
