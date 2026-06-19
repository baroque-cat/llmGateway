# pool-error-isolation

Detect pool-level HTTP/2 protocol errors (`httpx.LocalProtocolError`) in the provider and skip key penalization in gateway handlers for client-side errors.

## Requirements

### Requirement: Provider detects pool-level HTTP/2 protocol errors

`AIBaseProvider._send_proxy_request()` SHALL detect `httpx.LocalProtocolError` and classify it as `ErrorReason.BAD_REQUEST` — a client-side error that does not trigger retry or key penalization.

#### Scenario: Pool-saturated LocalProtocolError captured

- **WHEN** `_send_proxy_request()` catches an `httpx.RequestError` and `isinstance(e, httpx.LocalProtocolError)` is `True`
- **THEN** the error is classified as `ErrorReason.BAD_REQUEST` with detail `" — connection pool saturated (all HTTP/2 streams in use)"`, a 503-synthetic `RequestErrorResponse` is returned, and no key penalty is applied

#### Scenario: Other RequestError subclasses unchanged

- **WHEN** `_send_proxy_request()` catches an `httpx.RequestError` that is NOT `httpx.LocalProtocolError` (e.g., `PoolTimeout`, `ConnectError`, `RemoteProtocolError`, `ReadTimeout`, `WriteTimeout`, `ConnectTimeout`, or plain `RequestError`)
- **THEN** the existing `isinstance` chain applies and classification continues as before (all mapping to `ErrorReason.NETWORK_ERROR`)

### Requirement: Gateway handlers skip key penalization for pool errors

The gateway's retry and non-retry request handlers SHALL skip key penalization when the error reason is a client-side error (`is_client_error() == True`), which includes `BAD_REQUEST` classified from pool-level `LocalProtocolError`.

#### Scenario: Full-stream handler skips penalty for BAD_REQUEST

- **WHEN** `_handle_full_stream_request()` receives a `CheckResult` with `error_reason == ErrorReason.BAD_REQUEST` and `is_client_error() == True`
- **THEN** the handler forwards the error to the client without calling `_report_key_failure()` or `cache.remove_key_from_pool()`

#### Scenario: Retry handler aborts immediately for BAD_REQUEST

- **WHEN** `_handle_buffered_retryable_request()` receives a `CheckResult` with `error_reason.is_client_error() == True`
- **THEN** the handler immediately aborts the retry loop and forwards the error to the client without consuming `server_error_attempts` or `key_error_attempts` counters
