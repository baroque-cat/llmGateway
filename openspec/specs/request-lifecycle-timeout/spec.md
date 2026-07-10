# request-lifecycle-timeout

## Purpose

Prevents indefinite request hangs in the gateway retry loop by enforcing a
total wall-clock deadline via `asyncio.timeout()`. Without this, a silent
upstream hang multiplied by retries can consume up to 20 minutes
(4 attempts × 300s read timeout) before the gateway returns an error.

## Requirements

### Requirement: Total request deadline enforced via asyncio.timeout
The gateway retry loop in `_handle_buffered_retryable_request()` SHALL enforce
a total wall-clock deadline using `asyncio.timeout()`, controlled by the
`timeouts.total` field in `TimeoutConfig`. The deadline SHALL cover all retry
attempts, backoff delays, and key rotation waits within the loop.

#### Scenario: Timeout fires during retry loop
- **WHEN** a provider has `timeouts.total: 600` and `retry.on_server_error.attempts: 3`,
  and the upstream hangs for 300s per attempt
- **THEN** after approximately 600s of cumulative wall-clock time (midway through
  the second retry attempt), `asyncio.TimeoutError` SHALL be raised
- **AND** the gateway SHALL return a 504 status code with a JSON body containing
  `error`, `attempts`, and `last_error` fields

#### Scenario: Timeout does not fire for fast failure
- **WHEN** a provider has `timeouts.total: 600` and the upstream returns a
  `NETWORK_ERROR` within 5s on every attempt, with 3 server retries and 3 key retries
- **THEN** the retry loop SHALL complete all retries normally without triggering
  `asyncio.TimeoutError`
- **AND** the normal retry exhaustion response SHALL be returned

#### Scenario: Backoff sleeps are counted within the deadline
- **WHEN** the retry loop sleeps for backoff delays (e.g.,
  `await asyncio.sleep(2.0)`) inside the `async with asyncio.timeout(...)` block
- **THEN** the sleep time SHALL count toward the total deadline

#### Scenario: Timeout exhaustion response includes structured data
- **WHEN** `asyncio.TimeoutError` is caught in the retry loop
- **THEN** the response SHALL be
  `JSONResponse(status_code=504, content={"error": "...", "attempts": <int>, "last_error": "<reason>"})`

### Requirement: timeouts.total field in TimeoutConfig
`TimeoutConfig` SHALL include a `total` field with a default of `600.0` seconds.
The field SHALL be validated as `gt=0`.

#### Scenario: Default total timeout is 600 seconds
- **WHEN** a provider omits the `timeouts` section from its config
- **THEN** `provider_config.timeouts.total` SHALL be `600.0`

#### Scenario: Custom total timeout from YAML
- **WHEN** the YAML config contains `timeouts: { total: 300.0, read: 120.0 }`
- **THEN** `provider_config.timeouts.total` SHALL be `300.0`

### Requirement: Timeout handler closes upstream response
When `asyncio.TimeoutError` is caught in `_handle_buffered_retryable_request()`,
the handler SHALL guarantee that the current `upstream_response` is closed via
`discard_response()` before returning the 504 JSONResponse. The closure SHALL
be implemented via a `finally` block wrapping the entire `async with asyncio.timeout()`
scope.

#### Scenario: Timeout fires with open upstream response
- **WHEN** `asyncio.timeout` fires while an upstream response is open
  (body_bytes is None, stream not yet forwarded or discarded)
- **THEN** `discard_response(upstream_response, body_bytes)` SHALL be called
  in the `finally` block
- **AND** `upstream_response.aclose()` SHALL be invoked
- **AND** the 504 JSONResponse SHALL be returned to the client

#### Scenario: Timeout fires after response already closed
- **WHEN** `asyncio.timeout` fires during `asyncio.sleep()` backoff after
  `discard_response()` has already been called on the current attempt
  (upstream_response is not None, body_bytes is not None, response already discarded)
- **THEN** `discard_response()` in `finally` SHALL be a safe no-op
  (body_bytes is not None, so discard_response returns without calling aclose())

#### Scenario: Timeout fires before any proxy_request call
- **WHEN** `asyncio.timeout` fires before the first `provider.proxy_request()` call
  (e.g., during initial `get_key_from_pool()` delay)
- **THEN** `upstream_response` SHALL be `None`
- **AND** the `finally` block SHALL skip `discard_response()` entirely

#### Scenario: discard_response failure is logged, not raised
- **WHEN** `discard_response()` in the `finally` block raises an exception
- **THEN** the exception SHALL be logged at ERROR level with `exc_info=True`
- **AND** the original `TimeoutError` SHALL NOT be masked
- **AND** the 504 JSONResponse SHALL still be returned

### Requirement: Per-stream timeout is primary defense, total is backstop
The gateway SHALL use the per-stream response header deadline (enforced by
`FixedHTTP2Connection` via `asyncio.wait_for`) as the **primary** defense against
stream starvation. The `asyncio.timeout(total)` deadline wrapping the retry loop
SHALL serve as the **backstop** — firing only when per-stream timeouts plus
retry attempts consume the total allotted time without resolving the error.

#### Scenario: Per-stream timeout fires before total deadline
- **WHEN** a provider has `timeouts.stream_read: 120` and `timeouts.total: 600`,
  and the upstream hangs without sending response headers
- **THEN** the per-stream timeout SHALL fire at approximately 120s
- **AND** the `NETWORK_ERROR` SHALL be returned to the retry loop
- **AND** the retry loop SHALL retry on a new stream
- **AND** the `asyncio.timeout(600)` SHALL NOT fire before retries are exhausted

#### Scenario: Total deadline fires when all retries time out
- **WHEN** a provider has `timeouts.stream_read: 120` and `timeouts.total: 600`,
  and retries are configured but every attempt hits the per-stream timeout
- **THEN** approximately 5 per-stream timeouts (120s each) SHALL occur within the 600s window
- **AND** if retries are exhausted, the gateway SHALL return an error
- **AND** if retries are NOT exhausted, the `asyncio.timeout(600)` SHALL fire
  and return a 504 with structured error data