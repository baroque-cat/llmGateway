# gateway-circuit-breaker — Delta Spec

## ADDED Requirements

### Requirement: Circuit breaker scope and lifecycle
The gateway SHALL implement a `KeyCircuitBreaker` state machine with states `CLOSED`, `OPEN`, and `HALF_OPEN` (new `BreakerState` StrEnum in `src/core/constants.py`). One breaker instance SHALL exist per provider instance per worker process. Breaker state SHALL be in-memory only: it SHALL NOT be persisted to the database, SHALL NOT be shared between workers, and SHALL reset to `CLOSED` with an empty window on worker restart. The pure state-machine logic SHALL live in `src/core/` with parameters in a frozen dataclass in `src/core/models.py`, following the `AdaptiveBatchController` precedent.

#### Scenario: Breaker state is per-worker
- **WHEN** worker A's breaker for a provider opens
- **THEN** worker B's breaker for the same provider SHALL remain unaffected

#### Scenario: Worker restart resets the breaker
- **WHEN** a worker process restarts
- **THEN** its breaker for every provider SHALL be `CLOSED` with an empty window

### Requirement: Breaker is active only in sticky mode
The breaker SHALL be consulted only when `gateway_policy.key_selection.mode` is `sticky` AND `gateway_policy.circuit_breaker.enabled` is true. In `round_robin` mode the breaker SHALL NOT influence selection, retries, or penalties regardless of its configuration.

#### Scenario: Round-robin mode ignores the breaker
- **WHEN** a provider uses `round_robin` mode with `circuit_breaker.enabled: true`
- **THEN** request handling SHALL behave exactly as before this change
- **AND** no breaker state SHALL be consulted or updated

#### Scenario: Breaker disabled in sticky mode
- **WHEN** a provider uses sticky mode with `circuit_breaker.enabled: false`
- **THEN** sticky selection and penalty semantics SHALL apply
- **AND** no breaker state transitions SHALL occur

### Requirement: Count-based sliding window
The breaker SHALL maintain a sliding window of the last `window_size` upstream attempt outcomes, where each outcome is success or failure with its final refined `ErrorReason`. The window SHALL be count-based (no timers). Only failures whose reason `is_retryable()` SHALL count as wave evidence; successes and non-retryable failures SHALL occupy window slots but SHALL NOT count toward the error share.

#### Scenario: Window evicts oldest outcomes
- **WHEN** `window_size` is 20 and 25 attempts have been recorded
- **THEN** the window SHALL contain only the 25 − 20 = most recent 20 outcomes

#### Scenario: Fatal and client errors are not wave evidence
- **WHEN** the window contains failures with `ErrorReason.INVALID_KEY` or `ErrorReason.BAD_REQUEST`
- **THEN** those failures SHALL NOT count toward the retryable-error share

### Requirement: Opening condition
While `CLOSED`, the breaker SHALL transition to `OPEN` when the window contains at least `min_samples` outcomes AND the share of retryable-error outcomes in the window is greater than or equal to `error_rate_threshold`.

#### Scenario: Threshold reached opens the breaker
- **WHEN** `window_size` is 20, `min_samples` is 5, `error_rate_threshold` is 0.5, and the last 6 outcomes are 3 retryable errors and 3 successes
- **THEN** the breaker SHALL transition to `OPEN`

#### Scenario: Below min_samples the breaker stays closed
- **WHEN** `min_samples` is 5 and only 4 outcomes have been recorded, all retryable errors
- **THEN** the breaker SHALL remain `CLOSED`

### Requirement: OPEN state fail-fast with transparent error forwarding
While `OPEN`, the gateway SHALL bypass the retry loop: exactly one upstream attempt SHALL be made, and on failure the upstream error response SHALL be forwarded to the client transparently. The gateway SHALL NOT synthesize a `503` or any gateway-generated error body in place of the upstream response.

#### Scenario: Fail-fast returns upstream error
- **WHEN** a request is served while the breaker is `OPEN` and the upstream returns an error
- **THEN** the upstream error response SHALL be forwarded to the client unchanged
- **AND** no retry of the request SHALL occur

### Requirement: OPEN state ban freeze
While `OPEN`, failures whose reason `is_retryable()` (including `RATE_LIMITED`) SHALL NOT trigger `_report_key_failure` and SHALL NOT remove the key from the pool. Fatal errors SHALL still ban and remove the key regardless of breaker state.

#### Scenario: Retryable failure during OPEN does not ban
- **WHEN** a request fails with `ErrorReason.RATE_LIMITED` while the breaker is `OPEN`
- **THEN** `_report_key_failure` SHALL NOT be called
- **AND** the key SHALL remain in the pool

#### Scenario: Fatal failure during OPEN still bans
- **WHEN** a request fails with `ErrorReason.INVALID_KEY` while the breaker is `OPEN`
- **THEN** `_report_key_failure` SHALL be called
- **AND** the key SHALL be removed from the pool

### Requirement: OPEN state round-robin fallback
While `OPEN` (including `HALF_OPEN`), the sticky pointer SHALL be released and key selection SHALL use round-robin rotation so that probe traffic spreads across the pool instead of concentrating on one key.

#### Scenario: Probe traffic rotates keys
- **WHEN** 3 consecutive probe requests are served while the breaker is `OPEN` or `HALF_OPEN`
- **THEN** the requests SHALL use round-robin key selection
- **AND** the sticky pointer SHALL NOT bind any of them

### Requirement: Cooldown and HALF_OPEN recovery
After `open_duration_sec` elapses since entering `OPEN`, the breaker SHALL transition to `HALF_OPEN`. In `HALF_OPEN`, `probe_successes_to_close` consecutive successful upstream attempts SHALL transition the breaker to `CLOSED` and re-engage sticky selection, with the sticky pointer bound to the last successful key. Any retryable failure in `HALF_OPEN` SHALL return the breaker to `OPEN` with the cooldown duration multiplied by `backoff_factor`, capped at `max_open_duration_sec`. A successful close SHALL reset the cooldown duration to the configured base `open_duration_sec`.

#### Scenario: Successful probes close the breaker
- **WHEN** the breaker is `HALF_OPEN` with `probe_successes_to_close: 3` and 3 consecutive requests succeed
- **THEN** the breaker SHALL transition to `CLOSED`
- **AND** sticky selection SHALL re-engage with the pointer bound to the last successful key

#### Scenario: Failed probe re-opens with exponential cooldown
- **WHEN** the breaker is `HALF_OPEN` with current cooldown 30 s and `backoff_factor: 2.0`, and a probe fails with a retryable error
- **THEN** the breaker SHALL return to `OPEN`
- **AND** the next cooldown SHALL be 60 s

#### Scenario: Cooldown capped at maximum
- **WHEN** repeated re-openings multiply the cooldown beyond `max_open_duration_sec`
- **THEN** the cooldown SHALL be clamped to `max_open_duration_sec`

### Requirement: Breaker observability
The gateway SHALL expose breaker metrics through `IMetricsCollector` compatible with both single-process and multiprocess Prometheus backends: state transitions (opened, closed, re-opened), requests served fail-fast while `OPEN`, and key rotations performed without ban. Metrics SHALL carry the provider instance label and use the `llm_gateway_` prefix.

#### Scenario: State transition increments counter
- **WHEN** a breaker transitions from `CLOSED` to `OPEN`
- **THEN** the opened-transitions counter for that provider SHALL increment by 1

#### Scenario: Fail-fast requests counted
- **WHEN** a request is served fail-fast while the breaker is `OPEN`
- **THEN** the fail-fast counter for that provider SHALL increment by 1

### Requirement: Circuit breaker configuration schema
The `GatewayPolicyConfig` schema SHALL include a `circuit_breaker` section (`CircuitBreakerConfig`) with fields: `enabled` (bool, default true), `window_size` (int, default 20, ge=1), `error_rate_threshold` (float, default 0.5, gt=0, le=1), `min_samples` (int, default 5, ge=1), `open_duration_sec` (float, default 30.0, gt=0), `backoff_factor` (float, default 2.0, ge=1.0), `max_open_duration_sec` (float, default 300.0, gt=0), `probe_successes_to_close` (int, default 3, ge=1). A model validator SHALL enforce `min_samples <= window_size` and `max_open_duration_sec >= open_duration_sec`. Defaults SHALL be provided in the three-tier defaults system and the annotated example config.

#### Scenario: Defaults applied when section omitted
- **WHEN** a provider config omits `circuit_breaker`
- **THEN** the defaults above SHALL apply

#### Scenario: Inconsistent window settings rejected
- **WHEN** `min_samples` exceeds `window_size`
- **THEN** config validation SHALL fail at load with a clear error message
