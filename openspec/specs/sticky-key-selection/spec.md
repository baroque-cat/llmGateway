# sticky-key-selection

## Purpose

Defines the optional per-provider sticky key selection mode for the Conductor
(API Gateway). In sticky mode each uvicorn worker keeps the same API key
across consecutive requests (per-worker, in-memory pointer) until a rotation
trigger fires, enabling provider-side prompt caching and full utilization of
one key's quota before moving on. The default mode remains `round_robin` with
behavior identical to before this capability was introduced.

## Requirements

### Requirement: Key selection mode is configurable per provider
The `GatewayPolicyConfig` schema SHALL include a `key_selection` section with a `mode` field accepting `round_robin` or `sticky` (new `KeySelectionMode` StrEnum in `src/core/constants.py`). The default SHALL be `round_robin`. When `round_robin` is active, key selection behavior SHALL be identical to the behavior prior to this change. The mode SHALL be overridable per provider instance.

#### Scenario: Default mode is round_robin
- **WHEN** a provider config omits `gateway_policy.key_selection`
- **THEN** the gateway SHALL select keys via round-robin rotation exactly as before this change

#### Scenario: Per-provider override to sticky
- **WHEN** provider `deepseek-main` sets `gateway_policy.key_selection.mode: sticky` and provider `gemini-production` does not
- **THEN** `deepseek-main` requests SHALL use sticky selection
- **AND** `gemini-production` requests SHALL continue to use round-robin selection

#### Scenario: Invalid mode rejected at config load
- **WHEN** a provider sets `gateway_policy.key_selection.mode: random`
- **THEN** Pydantic validation SHALL fail at config load with a clear error message

### Requirement: Sticky pointer is per-worker and in-memory
Each uvicorn worker process SHALL maintain its own sticky key pointer per provider instance. The pointer SHALL NOT be persisted to the database and SHALL NOT be shared between workers. A worker restart SHALL reset its sticky pointers.

#### Scenario: Two workers hold different sticky keys
- **WHEN** worker A and worker B both serve requests for the same provider in sticky mode
- **THEN** each worker SHALL independently establish and keep its own sticky key
- **AND** the two workers MAY hold different keys simultaneously

#### Scenario: Worker restart resets the pointer
- **WHEN** a worker process restarts
- **THEN** its sticky pointer for every provider SHALL be unset
- **AND** the next request SHALL establish a new pointer from the pool

### Requirement: Sticky selection returns the pointer key without rotating the pool
In sticky mode, when the sticky pointer is set and the key is present in the pool, key selection SHALL return the pointer's `(key_id, key_value)` without rotating the deque. When the pointer is unset, selection SHALL take a key from the pool and establish the pointer with it.

#### Scenario: Consecutive requests reuse the same key
- **WHEN** a worker in sticky mode serves 5 consecutive requests for a provider and no rotation trigger fires
- **THEN** all 5 requests SHALL use the same `(key_id, key_value)`

#### Scenario: Deque is not rotated by sticky selection
- **WHEN** sticky selection returns the pointer key
- **THEN** the provider's key deque SHALL NOT be rotated (no `popleft`/`append` for the selected key)

#### Scenario: First request establishes the pointer
- **WHEN** the sticky pointer for a provider is unset and a request arrives
- **THEN** selection SHALL take a key from the pool
- **AND** that key SHALL become the sticky pointer for subsequent requests

### Requirement: Sticky pointer survives cache refresh
After `refresh_key_pool()` rebuilds the provider's pool, the sticky pointer SHALL be re-validated by `key_id` against the new pool. If the `key_id` is present, the pointer SHALL be kept (with the key value refreshed from the new pool). If the `key_id` is absent, the pointer SHALL be cleared and the next request SHALL re-establish it.

#### Scenario: Pointer survives periodic refresh
- **WHEN** the 10-second cache refresh rebuilds the pool and the sticky key is still valid in the database
- **THEN** the sticky pointer SHALL remain bound to the same `key_id`
- **AND** subsequent requests SHALL continue to use that key

#### Scenario: Pointer cleared when key disappears from pool
- **WHEN** the cache refresh rebuilds the pool and the sticky `key_id` is no longer present (e.g., banned by Keeper or removed from config)
- **THEN** the sticky pointer SHALL be cleared
- **AND** the next request SHALL establish a new pointer from the rebuilt pool

### Requirement: Rotation triggers in sticky mode
Rotation decisions in sticky mode SHALL consume the final refined `ErrorReason` (after `error_parsing`) as the single source of truth. Client errors SHALL NOT rotate the pointer and SHALL NOT penalize the key. Fatal errors (`INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL`) and `OVERLOADED` SHALL rotate the pointer and ban the key. `RATE_LIMITED` SHALL rotate the pointer and ban the key. Server errors (`is_server_error()`: `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT`) SHALL rotate the pointer for the current request but SHALL NOT ban the key in the database and SHALL NOT remove it from the pool.

#### Scenario: Client error keeps the sticky key
- **WHEN** a request fails with `ErrorReason.BAD_REQUEST` (including pool-saturation `LocalProtocolError`)
- **THEN** the sticky pointer SHALL NOT change
- **AND** `_report_key_failure` SHALL NOT be called
- **AND** `remove_key_from_pool` SHALL NOT be called

#### Scenario: Fatal error rotates and bans
- **WHEN** a request fails with `ErrorReason.NO_QUOTA`
- **THEN** the sticky pointer SHALL rotate to a different key
- **AND** `_report_key_failure` SHALL be called for the failed key
- **AND** the failed key SHALL be removed from the pool

#### Scenario: Rate limit rotates and bans
- **WHEN** a request fails with `ErrorReason.RATE_LIMITED`
- **THEN** the sticky pointer SHALL rotate to a different key
- **AND** the failed key SHALL be banned via `_report_key_failure` and removed from the pool

#### Scenario: Server error rotates without ban
- **WHEN** a request fails with `ErrorReason.TIMEOUT` or `ErrorReason.SERVER_ERROR`
- **THEN** the sticky pointer SHALL rotate to a different key for the current request
- **AND** `_report_key_failure` SHALL NOT be called for the failed key
- **AND** the failed key SHALL remain in the pool for subsequent requests

### Requirement: Rotation re-establishes the pointer excluding the failed key
When a rotation trigger fires, the new sticky key SHALL be selected from the pool excluding the failed `key_id`. The newly selected key SHALL become the new sticky pointer. If no other key is available, selection SHALL return `None` and the gateway SHALL respond with the no-available-keys error as it does today.

#### Scenario: Rotation excludes the failed key
- **WHEN** sticky key `42` fails with a rotation trigger and keys `42`, `43`, `44` are in the pool
- **THEN** the new sticky pointer SHALL be key `43` or `44`
- **AND** key `42` SHALL NOT be the new pointer

#### Scenario: Pool exhausted during rotation
- **WHEN** the only key in the pool fails with a rotation trigger
- **THEN** selection SHALL return `None`
- **AND** the gateway SHALL return the same no-available-keys error response as in round-robin mode

### Requirement: Direct removal of the sticky key clears the pointer
When `remove_key_from_pool()` removes the key currently held by the sticky pointer, the pointer SHALL be cleared. The next request SHALL re-establish it from the remaining pool.

#### Scenario: External removal clears matching pointer
- **WHEN** `remove_key_from_pool("my-provider", key_id=42)` is called and the sticky pointer holds key `42`
- **THEN** the sticky pointer SHALL be cleared
- **AND** the next request SHALL establish a new pointer from the remaining keys

### Requirement: Full-stream path honors sticky mode
When `retry.enabled` is false and sticky mode is active, `_handle_full_stream_request()` SHALL select keys via the sticky pointer and SHALL apply the sticky rotation triggers on failure. No request retry SHALL occur. The upstream error SHALL be returned to the client.

#### Scenario: Full-stream error rotates pointer without retry
- **WHEN** a full-stream request fails with a rotation trigger in sticky mode
- **THEN** the sticky pointer SHALL rotate per the trigger classification
- **AND** the upstream error SHALL be returned to the client without any retry of the request

### Requirement: Sticky retry loop rotates the key and retries the request
When `retry.enabled` is true and sticky mode is active, `_handle_buffered_retryable_request()` SHALL NOT execute the same-key `on_server_error` retry branch. Any rotation trigger (fatal errors, `OVERLOADED`, `RATE_LIMITED`, and server errors) SHALL add the failed key to the request-local exclude set, increment `key_error_attempts`, apply the `on_key_error` backoff, and retry the REQUEST with a NEW key. The `on_server_error` configuration SHALL be ignored. The `asyncio.timeout(timeouts.total)` deadline SHALL still wrap the loop.

#### Scenario: Server error rotates key instead of same-key retry
- **WHEN** a sticky retry-loop request fails with `ErrorReason.SERVER_ERROR`
- **THEN** the failed key SHALL be added to the exclude set
- **AND** the request SHALL be retried with a different key
- **AND** no same-key retry attempt SHALL occur

#### Scenario: on_server_error config ignored in sticky mode
- **WHEN** a provider has sticky mode with `retry.on_server_error.attempts: 5`
- **THEN** the retry loop SHALL NOT perform up to 5 same-key attempts on server errors
- **AND** server errors SHALL consume `key_error_attempts` like other rotation triggers

#### Scenario: Client error aborts without consuming counters
- **WHEN** a sticky retry-loop request fails with `ErrorReason.BAD_REQUEST`
- **THEN** the loop SHALL abort and forward the error to the client
- **AND** neither `key_error_attempts` nor the sticky pointer SHALL change

### Requirement: Config validation for sticky mode with retry
When `key_selection.mode` is `sticky` and `retry.enabled` is true, `on_key_error.attempts` MUST be greater than 0. The `RetryPolicyConfig` validation SHALL enforce this for sticky providers; `on_server_error.attempts` alone SHALL NOT satisfy the requirement in sticky mode.

#### Scenario: Sticky retry without key-error attempts rejected
- **WHEN** a provider sets sticky mode with `retry.enabled: true` and `on_key_error.attempts: 0`
- **THEN** config validation SHALL fail at load with a clear error message
