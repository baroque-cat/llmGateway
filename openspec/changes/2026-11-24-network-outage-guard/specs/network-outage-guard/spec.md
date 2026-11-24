## Purpose

Detect a system-wide upstream network outage and pause gateway/keeper work
without corrupting key status.

## Requirements

### Requirement: Transport failures are never key faults

The system SHALL keep a key's `status` and `failing_since` unchanged when the
failure is a transport failure.

#### Scenario: Keeper probe times out

- **GIVEN** a key with `status = 'valid'`
- **WHEN** the keeper probe raises `ConnectTimeout`
- **THEN** `update_status` SHALL update only `last_checked`, `next_check_time`,
  `status_code`, `response_time`, and `error_message`
- **AND** `status` SHALL remain `'valid'`
- **AND** the key SHALL remain eligible for the gateway cache

#### Scenario: Gateway request fails with `RemoteProtocolError`

- **WHEN** a gateway attempt returns a `CheckResult` with
  `transport_class = 'remote_protocol'`
- **THEN** `_report_key_failure` SHALL NOT write a key status
- **AND** the retry loop SHALL NOT remove the key from the in-memory pool

### Requirement: Transport retries are bounded and do not consume key budgets

The gateway SHALL use `on_transport_error` for transport failures.

#### Scenario: First transport failure

- **GIVEN** `on_transport_error.attempts = 2`
- **WHEN** the first attempt fails with `ConnectTimeout`
- **THEN** the gateway SHALL evict the provider's HTTP client
- **AND** SHALL retry the same key after the transport backoff
- **AND** SHALL NOT increment `key_error_attempts` or `server_error_attempts`

#### Scenario: Transport budget exhausted

- **WHEN** the transport attempts are exhausted
- **THEN** the gateway SHALL forward the last upstream error
- **AND** SHALL NOT penalize the key

### Requirement: Global guard detects an outage and fails closed

The system SHALL pause upstream work when the guard is DOWN in `pause` mode.

#### Scenario: Passive detection in the gateway

- **GIVEN** `passive_min_providers = 3` and `passive_min_failures = 6`
- **WHEN** transport failures from three distinct providers are recorded within
  `passive_window_sec`
- **THEN** the guard SHALL transition to DOWN
- **AND** subsequent gateway requests SHALL return `503` with `Retry-After: 60`
- **AND** no provider SHALL be called

#### Scenario: Active detection in the keeper

- **GIVEN** `fail_threshold = 3`
- **WHEN** three consecutive active probe rounds fail
- **THEN** the keeper guard SHALL transition to DOWN
- **AND** `run_cycle` SHALL return before selecting resources
- **AND** no key status SHALL be written

#### Scenario: Keeper preflight failure

- **WHEN** fewer than `min_probe_successes` targets are reachable before a
  `run_cycle`
- **THEN** the cycle SHALL be aborted
- **AND** a DOWN marker SHALL be written

### Requirement: Cross-process coordination uses a TTL marker

The system SHALL coordinate gateway workers and the keeper through a JSON
marker on the shared `data/` volume.

#### Scenario: Gateway worker adopts a keeper marker

- **WHEN** the keeper writes a fresh DOWN marker
- **THEN** each gateway worker SHALL adopt DOWN within one poll interval
- **AND** SHALL start returning `503`

#### Scenario: Stale marker

- **GIVEN** a marker whose `expires_at` is in the past
- **WHEN** a process reads it
- **THEN** the marker SHALL be ignored
- **AND** a live process SHALL NOT auto-recover from its local DOWN state

### Requirement: Recovery requires an operator restart

The guard SHALL NOT auto-recover a running process.

#### Scenario: Network restored while the process is running

- **GIVEN** the guard is DOWN and `auto_recover = false`
- **WHEN** the active probe succeeds
- **THEN** the guard SHALL remain DOWN
- **AND** SHALL only refresh the marker

#### Scenario: Operator restarts the gateway

- **WHEN** the gateway starts and its startup probe succeeds
- **THEN** the guard SHALL be UP
- **AND** the marker SHALL be removed

#### Scenario: Operator restarts while the network is still down

- **WHEN** the gateway starts and its startup probe fails
- **THEN** the guard SHALL be DOWN
- **AND** a new marker SHALL be written
- **AND** no key SHALL be penalized

### Requirement: Health endpoints expose guard state

The gateway SHALL expose liveness and readiness.

#### Scenario: `/healthz`

- **WHEN** the process is alive
- **THEN** `/healthz` SHALL return 200

#### Scenario: `/readyz` while DOWN

- **WHEN** the guard is DOWN and enforcing
- **THEN** `/readyz` SHALL return 503
- **AND** the body SHALL include the guard snapshot
