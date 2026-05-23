## Context

The llmGateway Conductor currently has no total request lifecycle timeout. The retry loop in `_handle_buffered_retryable_request()` (`gateway_service.py:546-709`) uses a `while True` loop with per-attempt `httpx.Timeout` (300s `read` default). With `on_server_error.attempts=3`, a silent upstream hang consumes `4 × 300s = 1200s = 20 minutes` before retries are exhausted. During this time, the `StreamMonitor` is blocked on `aiter_bytes().__anext__()` producing zero log output — operators see a silent hang.

Network error logs are also uninformative: `"Upstream request failed with a network-level error: <exception>"` lacks exception type, URL, timing, or human-readable detail. Operators cannot distinguish a `ReadTimeout` from a `RemoteProtocolError` or `PoolTimeout` without enabling `DEBUG` logging.

Separately, httpx connection pool limits use httpx defaults (100 max connections, 20 keepalive, 5s expiry) with no configuration surface. Fire-and-forget DB tasks (`_report_key_failure`, `cache.refresh_key_pool()`) run with no `command_timeout`, risking indefinite hangs on a frozen database.

## Goals / Non-Goals

**Goals:**
- Add a configurable total request deadline (`asyncio.timeout`) around the gateway retry loop, returning structured 504 on exhaustion
- Enhance network error logging (exception type, URL, human-readable detail) at `ERROR` level without requiring `DEBUG`
- Add `asyncio.timeout()` support to the `TimeoutConfig` model as a `total` field
- Provide global HTTP client connection pool configuration (`max_connections`, `max_keepalive_connections`, `keepalive_expiry`) applicable to both Keeper and Gateway
- Provide independent httpx/httpcore log level control and optional per-request trace
- Add database `command_timeout` to prevent indefinite fire-and-forget task hangs
- Change `dedicated_http_client` default to `True` for connection pool isolation per provider

**Non-Goals:**
- Changing the `_handle_full_stream_request()` path (transparent proxy) — it has no retry loop, so `asyncio.timeout` is not applicable
- Changing `response.text` access patterns in `check()` methods — static analysis confirms all are safe (non-streaming requests, body pre-buffered by httpx)
- Adding per-chunk stream timeout warnings — out of scope; focus is on error path logging
- Changing retry policy defaults (retry remains opt-in per provider)
- Adding metrics for fire-and-forget task tracking (observability gap remains but is deferred)

## Decisions

### Decision 1: Use `asyncio.timeout` at the retry-loop level, not per-request level

**Chosen:** Wrap the entire `while True` retry loop in `_handle_buffered_retryable_request()` with `async with asyncio.timeout(total_sec)`.

**Alternatives considered:**
- **Per-request `httpx.Timeout(total=...)`**: httpx does not provide a `total` timeout. It uses four independent phase timeouts (`connect`, `read`, `write`, `pool`). Even if it did, this would not cover backoff sleeps between retries.
- **Wrap each `await provider.proxy_request()` individually**: Would not cover cumulative time across retries + backoffs.
- **Wrap with `asyncio.wait_for()`**: Same semantics as `asyncio.timeout` but less ergonomic (can't use as context manager around multiple awaits).

**Rationale:** `asyncio.timeout` (Python 3.11+) is the standard library mechanism for wall-clock deadlines on coroutine execution. It covers HTTP calls AND backoff sleeps seamlessly. When it fires, `asyncio.CancelledError` propagates into httpx, which converts it to a transport-level error — the except handler returns a clean 504.

### Decision 2: Add `total` to `TimeoutConfig`, not `GatewayPolicyConfig`

**Chosen:** `TimeoutConfig.total: float = Field(default=600.0, gt=0)` in `schemas.py`.

**Rationale:** Semantically, this is a timeout value, not a retry policy parameter. All other time values (`connect`, `read`, `write`, `pool`) live in `TimeoutConfig`. Consistency dictates `total` belongs there too. `GatewayPolicyConfig` is for behavioral policies (retry enabled/disabled, streaming mode, debug mode).

### Decision 3: Global `http_client` config section, not per-provider

**Chosen:** New top-level `http_client: HttpClientConfig` in `Config`, with nested `pool: HttpClientPoolConfig`. Applied via `HttpClientFactory` at client creation time.

**Alternatives considered:**
- **Per-provider under `ProviderConfig`**: `httpx.Limits` configures the `AsyncClient` instance, and clients can be shared across providers (when `dedicated_http_client: false`). Per-provider pool config would conflict on shared clients.
- **Environment variables (`HTTPX_MAX_CONNECTIONS`, etc.)**: httpx does not read these natively; would require custom code and lose YAML schema validation.

**Rationale:** Pool limits are process-wide — they govern the `httpx.AsyncClient` instance, not individual requests. By placing them in a top-level section (sibling to `database`, `logging`, etc.), both Keeper and Gateway factories read the same config. This matches the precedent of `DatabasePoolConfig` for asyncpg pool sizing.

### Decision 4: Enhanced error logging via `isinstance` chain, not regex parsing

**Chosen:** In `_send_proxy_request()` except block: classify `httpx.RequestError` subtypes via `isinstance()` checks, appending human-readable detail strings.

**Alternatives considered:**
- **Parse `str(e)` with regex to extract type name**: Brittle, locale-dependent, breaks on httpx message format changes.
- **Log only `type(e).__name__` without detail**: Still unambiguous but less operator-friendly.
- **Add a separate `logger.debug` for detail**: Would require `DEBUG` log level — operators need this at `INFO`/`ERROR`.

**Rationale:** `isinstance()` is the Pythonic way to discriminate exception types. The extra detail strings (`"no data received (read_timeout=300s)"`, `"HTTP/2 protocol error"`) make the ERROR log immediately actionable without grep or documentation lookup.

### Decision 5: `command_timeout` via asyncpg pool parameter, not per-query

**Chosen:** `command_timeout=30.0` passed to `asyncpg.create_pool()` in `init_db_pool()`. Overridden for `VACUUM ANALYZE` via `SET statement_timeout = 0`.

**Alternatives considered:**
- **Per-connection `.execute(timeout=...)`**: asyncpg's `timeout` parameter uses server-side `statement_timeout`, not client-side `command_timeout`. Different semantics — `command_timeout` guards against network hangs (DB unreachable), while `statement_timeout` guards against slow queries. We need the former.
- **Second pool without timeout for maintenance ops**: Over-engineering; a single `SET` statement before VACUUM is simpler.
- **Default of `None` with explicit per-call-site timeouts**: Error-prone — fire-and-forget tasks are easy to miss.

**Rationale:** Pool-level `command_timeout` provides a safety net for ALL queries, including fire-and-forget tasks like `_report_key_failure` and scheduled tasks like `cache.refresh_key_pool()`. The only operation that legitimately needs more time is `VACUUM ANALYZE`, which explicitly overrides the timeout.

### Decision 6: `httpcore_level: "WARNING"` by default

**Chosen:** New `logging.http_client` section with `httpcore_level: "WARNING"` default. httpx level remains `"WARNING"` (existing behavior preserved).

**Rationale:** httpcore currently inherits the root logger level (default `INFO`). At `INFO`, httpcore could produce verbose connection/SSL output. Setting it to `WARNING` by default prevents noise while allowing operators to set `"DEBUG"` for HTTP/2 protocol tracing. This is a defensive default — the existing behavior at INFO level should be preserved (no httpcore noise).

## Risks / Trade-offs

- **[Risk] `asyncio.timeout` fires mid-`client.send()` — could httpx leave a connection in bad state?** → Mitigation: `asyncio.CancelledError` triggers httpx's internal cleanup. The next attempt uses a fresh request. The `except asyncio.TimeoutError` handler creates a synthetic 504 response, so no dangling connection leaks to the client.
- **[Risk] Changing `dedicated_http_client` default from `False` to `True` increases TCP connection count per process.** → Mitigation: Each provider gets a private pool. For hosts with many providers on the same `api_base_url`, operators can explicitly set `dedicated_http_client: false`. The default pool size (100 connections) per provider is generous.
- **[Risk] `command_timeout=30` could kill legitimate slow queries during initial schema setup.** → Mitigation: Schema creation (`CREATE TABLE IF NOT EXISTS`) runs once at startup and is idempotent. All queries complete in <1s. `VACUUM ANALYZE` explicitly overrides the timeout. No migration scripts or bulk operations exist.
- **[Trade-off] The `total` timeout default (600s) applies to ALL providers unless overridden.** With `connect=15`, `read=300`, `write=35`, `pool=35` (sum = 385s per attempt), 600s allows ~1.5 attempts. Operators wanting more retries should raise `total` proportionally. This is a deliberate nudge toward faster failure.
