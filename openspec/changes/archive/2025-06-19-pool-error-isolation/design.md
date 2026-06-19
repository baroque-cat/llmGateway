## Context

The llmGateway's error classification pipeline maps `httpx.RequestError` exceptions to `ErrorReason` in `AIBaseProvider._send_proxy_request()` (`src/providers/base.py:286`). Currently, `httpx.LocalProtocolError` falls through all `isinstance` checks and lands in the `else` branch, mapping to `ErrorReason.NETWORK_ERROR` — a retryable server error. The gateway's retry logic then retries with the same key (up to 3 times), and after exhaustion penalizes the key.

The root cause is that `httpx.LocalProtocolError` is a **sibling** (not subclass) of `httpx.RemoteProtocolError`. The `isinstance(e, httpx.RemoteProtocolError)` check on line 298 does NOT match `LocalProtocolError`, so it falls through.

With the `src/core/http2/` package (backporting upstream PRs #1022 and #1088), `LocalProtocolError` from pool saturation is now unlikely but still possible (e.g., cancellation during `send_request_headers`). When it does occur, penalizing the key is categorically wrong — the failure is local infrastructure, not an upstream API problem.

Additionally, operators have no visibility into pool/stream health at runtime. The `CapacityAwareHttp2Pool` tracks rich state internally (connections, active streams, queued requests) but none of it is exposed via logging.

**Constraint:** The change must be minimal — a single-file fix with no gateway-handler changes, no new `ErrorReason` values, no config schema migrations.

## Goals / Non-Goals

**Goals:**
1. Prevent pool-level `LocalProtocolError` from triggering key penalization in both gateway handlers (`_handle_full_stream_request` and `_handle_buffered_retryable_request`)
2. Add periodic INFO-level logging of pool health (connections, streams, queued requests) per provider
3. Keep the change minimal — leverage existing `ErrorReason` classification and gateway handler logic
4. Make health logging interval configurable with a sensible default (60 s)

**Non-Goals:**
- Add a new `ErrorReason` enum value (e.g., `POOL_SATURATED`) — deferred to a follow-up
- Change the retry policy or gateway handler control flow
- Expose pool metrics via Prometheus (logging only)
- Implement pool health logging in Keeper mode (gateway only)
- Change `CapacityAwareHttp2Pool` routing algorithm

## Decisions

### Decision 1: Map `LocalProtocolError` → `BAD_REQUEST` in `_send_proxy_request`

**Chosen:** Add an `isinstance(e, httpx.LocalProtocolError)` check in `_send_proxy_request` (after the `RemoteProtocolError` check) and map it to `ErrorReason.BAD_REQUEST`.

**Why:** `BAD_REQUEST.is_client_error() == True`. Both gateway handlers already have `is_client_error()` checks that immediately abort retry and skip key penalization. No gateway changes needed — the existing control flow handles this correctly.

**Alternatives considered:**
- *New `ErrorReason.POOL_SATURATED`* — semantically precise but requires ~40 lines across 5 files + config schema migration. Overkill for a condition that is now rare with the `src/core/http2/` fix.
- *Map to `ErrorReason.UNKNOWN`* — also `is_client_error() == True`, but semantically misleading.
- *Map to `ErrorReason.SERVICE_UNAVAILABLE`* — would be wrong: `is_server_error() == True`, `is_retryable() == True` → key still gets penalized.
- *Catch in `CapacityAwareHttp2Transport`* — transport layer shouldn't know about gateway error classification.

**Risk mitigation:** The error message logged at `logger.error(...)` in `_send_proxy_request` includes the detail string `" — connection pool saturated (all HTTP/2 streams in use)"` — operators can distinguish real `BAD_REQUEST` from pool-saturation in logs.

### Decision 2: Health logging follows `_cache_refresh_loop` pattern

**Chosen:** Create a background asyncio task `_pool_health_log_loop()` in the gateway lifespan (`create_app()`), mirroring the existing `_cache_refresh_loop` pattern.

**Why:** The gateway already has precedent for periodic background tasks (`_cache_refresh_loop` at 10 s interval). Same lifecycle management (create in startup, cancel in shutdown). No scheduler dependency needed.

**Alternatives considered:**
- *APScheduler job* — heavier; the Keeper uses APScheduler for multi-minute intervals, but a simple `asyncio.sleep()` loop is sufficient for 60 s intervals.
- *Middleware-based logging* — would fire on every request, adding noise at high concurrency. Periodic summary is more useful for operators.
- *Prometheus metrics only* — metrics are great for dashboards/alerts but don't provide the at-a-glance operator view that INFO log lines offer.

### Decision 3: Access private pool internals from within same module hierarchy

**Chosen:** `HttpClientFactory.get_pool_health_summary()` reaches into `client._transport._pool` to call `CapacityAwareHttp2Pool.get_health_summary()`. Similarly, `get_health_summary()` accesses `conn._connection` to distinguish H2 from H1 and read stream counts.

**Why:** `HttpClientFactory` creates and owns the clients — it knows the exact types. There is no public httpx API for pool statistics. Accessing `_transport._pool` from within the project's own code is safe because we control both sides of the contract.

**Alternatives considered:**
- *Add public methods to httpx upstream* — not practical for this change.
- *Track pool state externally* — duplicate bookkeeping; the pool already has the data.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **`BAD_REQUEST` semantics imprecise** — operators see `BAD_REQUEST` in logs for what is actually pool saturation | The `error_message` log line includes `" — connection pool saturated (all HTTP/2 streams in use)"`. A future change can introduce `POOL_SATURATED`. |
| **Other `httpx.LocalProtocolError` sources** — if httpx adds non-pool `LocalProtocolError` sources, they'd also bypass key penalization | `LocalProtocolError` is exclusively raised for h2 protocol errors local to the client — all such errors are infrastructure issues, not key issues. |
| **Health logging accesses private httpx attributes** — `client._transport` is private API | `HttpClientFactory` creates the client with a known transport type. The access is within the same codebase that defines the type. Test coverage validates the contract. |
| **`_pool_health_log_loop` crash silently terminates logging** | `except Exception` handler prevents crash propagation. Failed iteration is logged at ERROR level. Next interval retries. |
| **Health logging creates noise at high client counts** | One log line per cached client per interval. With `dedicated_http_client=True`, this equals one line per provider. Within operational norms (< 20 providers), negligible. |
