## Context

The deployment is `container -> host TUN -> Xray VLESS/XHTTP -> RU -> Riga ->
Amsterdam`. The Python application sees only httpx-level symptoms. The keeper
is a single process and owns all bulk key-status writes; the gateway may run
one or more uvicorn workers, each with its own in-memory cache and breaker.

Two failure classes must be separated:

1. **Provider/key failure** — an HTTP response with a provider error.
2. **Transport failure** — no usable HTTP response: connect/TLS timeout,
   connection reset, protocol break, or a stale XHTTP carrier.

## Goals

- Never demote a key because of a transport failure.
- Retry transport failures quickly, with a fresh HTTP client, without
  consuming key/server-error budgets.
- Detect a system-wide outage (all/most providers unreachable) and pause both
  gateway and keeper.
- In `pause` mode, reset only on operator action (container restart + startup
  probe), not by time-based auto-recovery. `log` mode is observational and
  auto-recovers when probes succeed again.
- Work with `GATEWAY_WORKERS=1` today and not collapse when workers > 1.
- Keep the per-provider `KeyCircuitBreaker` unchanged; compose the new guard
  outside it.

## Non-goals

- Fixing XHTTP stale sockets inside the Python application. That is an Xray
  `splithttp` concern; this change only mitigates and detects it.
- Recovering a stream that already sent headers to the client.
- Persisting a durable "network is down" fact in PostgreSQL.

## Transport classification

`TransportFailureClass` values:

| httpx exception | Class |
|---|---|
| `PoolTimeout` | `pool_timeout` |
| `ConnectTimeout` | `connect_timeout` |
| `ConnectError` | `connect_error` |
| `ReadTimeout` with `"Per-stream timeout"` | `stream_read_timeout` |
| `ReadTimeout` | `read_timeout` |
| `WriteTimeout` | `write_timeout` |
| `RemoteProtocolError` | `remote_protocol` |
| `LocalProtocolError` | `pool_saturated` |
| other `RequestError` | `request_error` |

`CheckResult.transport_class` is `None` for HTTP-status failures and
successes. `LocalProtocolError` keeps `ErrorReason.BAD_REQUEST` for backward
compatibility but is treated as a transport event by the retry/guard layers.

## Retry semantics

- `on_transport_error` default: `attempts=2`, `backoff_sec=0.3`,
  `backoff_factor=2.0`.
- A transport failure:
  - does not increment `key_error_attempts` or `server_error_attempts`;
  - does not call `_report_key_failure` or `remove_key_from_pool`;
  - keeps the same key (all keys share the tunnel, so rotating would only
    risk exhausting a small pool);
  - evicts the provider's `httpx.AsyncClient` once per request (new pool);
  - sleeps the transport backoff and continues.
- Exhaustion forwards the last upstream error; no key penalty.
- `retry.enabled=false` and debug mode zero all attempt budgets (the existing
  startup warning is now true).

### HTTP client eviction

`HttpClientFactory.evict(provider)`:

- removes the client from `_clients` immediately, so new requests create a
  new `AsyncClient` and a new TCP/TLS connection;
- moves the old client to `_retired_clients` and closes it after 30 s, so
  in-flight streams can finish;
- `close_all()` closes both active and retired clients.

## Keeper write semantics

`KeyRepository.update_status(..., transport_failure=True)` updates only:

- `last_checked`
- `next_check_time`
- `status_code`
- `response_time`
- `error_message`

It does **not** touch `status` or `failing_since`. A key that was `valid`
stays `valid` and remains eligible for the gateway cache. Recovery therefore
does not depend on waiting for `on_server_error_min`.

`_report_key_failure` also returns early for transport failures.

## 400 probe mapping

A 400 from a health probe no longer maps to `INVALID_KEY`. It maps through
the normal status-code table (`BAD_REQUEST`), so a bad `test_payload` or a
proxy/middlebox cannot ban the whole pool for 10 days. Providers can still
reclassify via `error_parsing.rules` when the body clearly indicates a key
problem.

## Network guard

### State

Process-local `UP`/`DOWN`. `pause` mode has no auto-recovery while the process
is alive; `log` mode auto-recovers after a successful probe because it never
blocks traffic. Transitions:

- `startup_probe` success -> UP (and marker removed)
- `startup_probe` failure -> DOWN (marker written)
- passive window / active probe / keeper preflight -> DOWN
- active probe success in `log` mode -> UP (marker removed)
- operator restart -> new process -> startup probe decides

`mode: "log"` records state and metrics but does not block requests/probes.
`mode: "pause"` enforces 503/pause.

### Signals

| Signal | Owner | Threshold |
|---|---|---|
| Passive transport window | each gateway worker | >= 3 distinct providers and >= 6 failures in 60 s |
| Active TCP+TLS probe | keeper (single) | 3 consecutive failed rounds, 30 s apart |
| Keeper preflight | keeper, before each `run_cycle` | < 2 of 3 targets reachable in 2 s |
| Keeper per-batch check | keeper, between batches | marker/local DOWN |

Active probes use `asyncio.open_connection` with TLS and a 3 s timeout. The
verdict covers DNS resolution plus the TCP/TLS handshake; closing the socket is
best-effort and is not part of the probe budget. No HTTP request or API key is
used.

### Shared marker

Path: `/app/data/network_guard/state.json` (both containers mount `./data`).

```json
{
  "state": "down",
  "source": "keeper",
  "pid": 12345,
  "since": 1795542498.0,
  "reason": "active_probe",
  "expires_at": 1795542588.0,
  "evidence": {
    "failed_probes": [{"url": "https://provider.example", "error": "TimeoutError: ..."}]
  }
}
```

- Written atomically (temp file + `fsync` + `os.replace`).
- TTL: `max(2 * probe_interval_sec, 60)`.
- Readers cache the marker for 1 s in a background loop; no file I/O in the
  request hot path.
- In `pause` mode a live process never auto-recovers when the marker
  disappears; only a restart does. In `log` mode a missing/expired marker or a
  successful active probe clears the local DOWN state.
- At startup, a successful probe clears the marker (the operator reset path).
  With no `probe_urls` configured, the startup probe does not clear an
  existing marker; the poll loop adopts it.

### Gateway behavior

- `catch_all_endpoint`: after auth, before provider dispatch, if
  `guard.enforcing and guard.is_down()` -> `503` with `Retry-After: 60` and a
  message telling the operator to fix connectivity and restart.
- No key selection, no upstream call, no DB write in this path.
- `/healthz` always 200 while the process is alive.
- `/readyz` 503 while the guard is DOWN; 200 otherwise.

### Keeper behavior

- `run_cycle`: if guard DOWN -> log once and return before selecting resources.
- `_process_provider_batch`: check guard before each batch; abort the rest.
- `_update_resource_status`: `transport_failure = result.transport_class is not
  None or (guard_down and not result.ok)`.
- Active probe loop runs independently of the key-probe schedule, so the
  guard can still observe/recover at startup even when key probes are paused.

### Multi-worker

- Each uvicorn worker has its own `NetworkGuard`; the marker coordinates them.
- Startup probes may run in each worker (3 targets x N, acceptable). A future
  optimization is a `startup.lock` + `startup.result` file; not required for
  the current `GATEWAY_WORKERS=1` deployment.
- Passive thresholds are best-effort per worker; the keeper active probe is
  the primary detector.
- The per-provider breaker remains per-worker; the guard is the global stop.

### Why not Redis/DB

A shared file on an already-mounted volume is enough for one host and adds no
dependency. Cross-host deployments should use a `system_state` table or Redis
in a follow-up.

## Metrics

| Metric | Type | Labels |
|---|---|---|
| `llm_gateway_upstream_attempts_total` | counter | `provider`, `outcome` |
| `llm_gateway_transport_failures_total` | counter | `provider`, `transport_class` |
| `llm_gateway_stream_disconnects_total` | counter | `provider` |
| `llm_gateway_network_down` | gauge | none |
| `llm_gateway_guard_trips_total` | counter | `reason` |

## Async flow / locks

- `NetworkGuard` methods are called from one event loop per process. Marker
  writes go through `asyncio.to_thread`; no lock is needed inside the process.
- Cross-process writes are last-wins via `os.replace`.
- `HttpClientFactory.evict` uses the existing per-provider creation lock only
  for creation; eviction is a dict pop and a background close task.
- No new lock ordering with the DB pool or breaker.

## Rollout

1. Deploy with `network_guard.enabled: false` (no behavior change).
2. Enable `mode: "log"`; collect metrics/logs for 1-2 days.
3. Enable `mode: "pause"` for gateway; keep keeper paused via the marker.
4. Enable keeper preflight/pause.
5. Only then consider `GATEWAY_WORKERS > 1`.

Rollback: set `network_guard.enabled: false` and
`on_transport_error.attempts: 0`; restart. No DB migration to revert.

## Test fixtures

- New `CanonicalConfig` fields for the guard.
- `NetworkGuardConfig` built from canonical values; marker path under
  `tmp_path`.
- Fake clock for TTL/passive windows.
- Local `asyncio.start_server` for probe success; a closed port for failure.
- No production URLs in tests (gatekeeper always bans them).
