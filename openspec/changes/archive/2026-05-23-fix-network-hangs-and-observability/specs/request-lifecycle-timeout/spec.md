## ADDED Requirements

### Requirement: Total request deadline enforced via asyncio.timeout
The gateway retry loop in `_handle_buffered_retryable_request()` SHALL enforce a total wall-clock deadline using `asyncio.timeout()`, controlled by the `timeouts.total` field in `TimeoutConfig`. The deadline SHALL cover all retry attempts, backoff delays, and key rotation waits within the loop.

#### Scenario: Timeout fires during retry loop
- **WHEN** a provider has `timeouts.total: 600` and `retry.on_server_error.attempts: 3`, and the upstream hangs for 300s per attempt
- **THEN** after approximately 600s of cumulative wall-clock time (midway through the second retry attempt), `asyncio.TimeoutError` SHALL be raised
- **AND** the gateway SHALL return a 504 status code with a JSON body containing `error`, `attempts`, and `last_error` fields

#### Scenario: Timeout does not fire for fast failure
- **WHEN** a provider has `timeouts.total: 600` and the upstream returns a `NETWORK_ERROR` within 5s on every attempt, with 3 server retries and 3 key retries
- **THEN** the retry loop SHALL complete all retries normally without triggering `asyncio.TimeoutError`
- **AND** the normal retry exhaustion response SHALL be returned

#### Scenario: Backoff sleeps are counted within the deadline
- **WHEN** the retry loop sleeps for backoff delays (e.g., `await asyncio.sleep(2.0)`) inside the `async with asyncio.timeout(...)` block
- **THEN** the sleep time SHALL count toward the total deadline

#### Scenario: Timeout exhaustion response includes structured data
- **WHEN** `asyncio.TimeoutError` is caught in the retry loop
- **THEN** the response SHALL be `JSONResponse(status_code=504, content={"error": "...", "attempts": <int>, "last_error": "<reason>"})`

### Requirement: timeouts.total field in TimeoutConfig
`TimeoutConfig` SHALL include a `total` field with a default of `600.0` seconds. The field SHALL be validated as `gt=0`.

#### Scenario: Default total timeout is 600 seconds
- **WHEN** a provider omits the `timeouts` section from its config
- **THEN** `provider_config.timeouts.total` SHALL be `600.0`

#### Scenario: Custom total timeout from YAML
- **WHEN** the YAML config contains `timeouts: { total: 300.0, read: 120.0 }`
- **THEN** `provider_config.timeouts.total` SHALL be `300.0`
