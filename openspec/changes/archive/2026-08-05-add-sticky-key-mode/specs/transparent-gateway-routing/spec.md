# transparent-gateway-routing — Delta Spec

## ADDED Requirements

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
