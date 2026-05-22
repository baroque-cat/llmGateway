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
