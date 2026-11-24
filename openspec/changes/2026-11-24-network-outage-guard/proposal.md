## Why

The gateway and keeper currently treat a dead upstream network as a series of
per-key failures. Transport errors are classified as retryable, but the
round-robin retry loop eventually penalizes the key, the keeper writes
`timeout`/`network_error` statuses, and the in-memory key pool is populated
only from `status = 'valid'`. A tunnel outage therefore empties the pool and
produces `503 No available API keys`, even though no key is at fault. A 400
from a probe payload (or a captive-portal 401/403) can be misclassified as
`invalid_key` and ban keys for 10 days.

At the same time, the XHTTP transport below the container can hand the
application a stale outer socket: httpx sees `ConnectTimeout`,
`RemoteProtocolError`, or `ReadTimeout`, but the application has no way to
distinguish "provider is down" from "our tunnel is down", and its retries
reuse the same cached HTTP/2 connection.

This change adds an explicit transport taxonomy, transport-aware retries that
never penalize a key, a keeper write path that does not demote keys on
transport failures, and a global network-outage guard that pauses both
processes until an operator fixes connectivity and restarts the container.

## What Changes

- **Transport failure classification**: new `TransportFailureClass` enum
  attached to `CheckResult`; every httpx transport exception is mapped to a
  stable class (`connect_timeout`, `connect_error`, `read_timeout`,
  `stream_read_timeout`, `remote_protocol`, `pool_saturated`, ...).
- **Transport-aware retry policy**: new `gateway_policy.retry.on_transport_error`
  budget. Transport failures rotate the key for the current request, evict the
  provider's HTTP client to force a fresh connection, and never write a key
  penalty.
- **Keeper semantics**: transport failures update only check metadata
  (`last_checked`, `next_check_time`, status code, message); `status` and
  `failing_since` stay unchanged. A 400 probe response is no longer treated
  as `INVALID_KEY`.
- **Network outage guard**: new `network_guard` config section, a process-local
  `NetworkGuard` state machine, a shared TTL marker under `./data`, active
  TCP+TLS probing in the single keeper process, passive detection in gateway
  workers, `/healthz` + `/readyz`, and 503 fail-closed behavior in `pause`
  mode.
- **Metrics**: upstream attempts by outcome, transport failures by class,
  stream disconnects, guard DOWN gauge and trip counter.
- **Config/docs**: `network_guard` defaults, `on_transport_error` defaults,
  example config, and this OpenSpec change.

## Capabilities

### New Capabilities

- `transport-failure-classification`: maps httpx transport exceptions to a
  stable phase/class and exposes it on `CheckResult`.
- `network-outage-guard`: detects a dead upstream network, pauses gateway and
  keeper work, coordinates across processes with a TTL marker, and resets only
  on restart/startup probe.

### Modified Capabilities

- `gateway-circuit-breaker`: transport failures no longer count as key-fault
  evidence and do not consume the server-error/key-error budgets.
- `provider-key-pool`: a transport failure does not change a key's `status`
  and therefore does not remove it from the cache.
- `request-lifecycle-timeout`: transport retries are bounded by the existing
  total request deadline.

## Impact

- **Config schema** (`src/config/schemas.py`): new `NetworkGuardConfig`;
  `RetryPolicyConfig.on_transport_error`; root `Config.network_guard`.
- **Config defaults** (`src/config/defaults.py`): guard and transport retry
  defaults.
- **Config accessor** (`src/core/accessor.py`): `get_network_guard_config()`.
- **Core** (`src/core/`): `TransportFailureClass` in `constants.py`;
  `CheckResult.transport_class`; new `network_guard.py`; guard checks in
  `probes.py`.
- **Providers** (`src/providers/`): transport classification in
  `base.py` and all three adapters; 400 probe mapping changed to
  `BAD_REQUEST`.
- **Gateway** (`src/services/gateway/`): transport branch in sticky and
  round-robin retry loops; `observe_upstream_attempt`; HTTP client eviction;
  guard gate in `catch_all_endpoint`; `/healthz`, `/readyz`.
- **Keeper** (`src/services/`): guard instance/active loop; transport-safe
  status writes in `key_probe.py`.
- **Database** (`src/db/database.py`): `update_status(transport_failure=True)`
  variant that does not touch `status`/`failing_since`.
- **Metrics** (`src/metrics/`): new metric names and descriptions.
- **Tests**: new unit/integration/stress coverage; existing provider tests
  updated for the new log field and 400 mapping.
- **No new dependencies.**

## Migration

- The guard is disabled by default (`network_guard.enabled: false`). Existing
  behavior is unchanged until an operator adds the section and enables it.
- `on_transport_error` defaults (`attempts: 2`) apply only when a provider
  enables retry; existing `on_key_error`/`on_server_error` budgets are
  unchanged.
- No database schema migration is required for the guard. The keeper change
  reuses existing columns.
