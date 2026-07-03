## Context

The HTTP/2 connection pool (`CapacityAwareHttp2Pool`) trusts the server-advertised
`SETTINGS_MAX_CONCURRENT_STREAMS` (typically 100, from the h2 library default). When
a provider has a hidden internal concurrency limit lower than 100 (e.g., qwen-home
processes only 8 concurrently), all excess streams queue on a single TCP connection.
The socket-level read timeout (120 s) does not fire for starved streams because data
for active streams keeps the socket busy. Only the 600 s wall-clock timeout kills
them — minutes of total freeze.

Stress tests in `tests/stress/test_cascading_freeze.py` already prove this behavior
(abrupt freeze, cascading backlog, silent read timeout). This change introduces the
fix: a per-provider cap on effective `max_concurrent_streams` per connection.

The `dedicated_http_client` field (default `True`, never set to `False` in any
example config) adds complexity without value. Removing it simplifies the cache-key
logic and eliminates the known `__none__` collision vulnerability (SEC-2 test).

## Goals / Non-Goals

**Goals:**
- Prevent the cascading freeze by capping streams per connection per provider
- Force the pool to open new TCP connections when the cap is reached
- Provide per-connection observability via labels and health breakdown
- Remove the dead `dedicated_http_client` code path

**Non-Goals:**
- Per-stream asyncio timeout in full-stream mode (separate change)
- Latency-based connection routing (rejected — false positives with LLM APIs)
- Full per-provider `HttpClientConfig` (only the cap field is per-provider; pool
  limits remain global)
- Prometheus metrics for connections (logs-only, as currently)

## Decisions

### Decision 1: Cap field in `ProviderConfig`, not `HttpClientConfig`

**Choice:** Add `max_concurrent_streams_per_connection: int = Field(default=5, ge=1, le=1000)`
to `ProviderConfig`.

**Rationale:** The problem is provider-specific (qwen-home has hidden limit ~8, OpenAI
handles 100+). A global cap would force all providers to the same conservative value.
Per-provider allows qwen=5 (default), openai=100 (override).

**Alternative considered:** Global field in `HttpClientConfig`. Rejected because it
cannot be overridden per-provider without also adding per-provider http_client config
(a much larger change).

### Decision 2: Default value of 5

**Choice:** `default=5`.

**Rationale:** 5 is conservative enough to prevent the bottleneck for any provider
with an internal limit ≥5, while not opening excessive TCP connections for
low-traffic providers. Providers that can handle more (OpenAI, Anthropic) override
in YAML. The actual effective cap is `min(config_value, server_advertised,
local_settings=100)`, so if a server advertises 3, the cap becomes 3.

**Alternative considered:** `default=None` (no cap, current behavior). Rejected
because the problem would persist for providers where operators forget to set the
field. A safe default is better than an unsafe one.

### Decision 3: Connection labels as `{provider_name}-conn-{ordinal}`

**Choice:** Each connection created by the pool receives a label string
`{provider_name}-conn-{ordinal}` where ordinal is a per-pool monotonic counter
starting at 0.

**Rationale:** Human-readable, correlates connections to providers in logs and health
output. The ordinal distinguishes multiple connections to the same host. The label
is stored on `CapacityAwareHTTPConnection` and surfaced in `get_health_summary()`.

**Alternative considered:** UUID-based IDs. Rejected — not human-readable, harder to
correlate in logs.

### Decision 4: Remove `dedicated_http_client` entirely

**Choice:** Delete the field from `ProviderConfig`, simplify
`_get_cache_key_for_provider` to always `return provider_name`, delete
`_get_cache_key_for_proxy`.

**Rationale:** All 4 example providers set `dedicated_http_client: true`. The `False`
path is never used in production. Removing it eliminates 21 lines of dead code, the
known `__none__` collision vulnerability, and ~12 tests that test dead behavior. The
`get_proxy_config()` accessor is still needed for client creation (proxy URL kwarg),
just not for cache-key derivation.

**Alternative considered:** Keep the field but deprecate it. Rejected — adds
complexity for no value; a clean break is simpler.

### Decision 5: Cap applied in `FixedHTTP2Connection`, not in the pool

**Choice:** The cap value is passed through the chain and applied in
`FixedHTTP2Connection._receive_remote_settings_change` (the `min()` call) and
`handle_async_request` (semaphore initialization).

**Rationale:** The H2 connection is where `_max_streams` is computed and the semaphore
is sized. Applying the cap there means `max_concurrent_requests()` returns the capped
value, and the pool's existing `_max_concurrent_requests(conn)` check naturally
respects it — no pool-level changes needed for the cap logic itself.

**Alternative considered:** Cap in the pool's `_max_concurrent_requests()` wrapper.
Rejected — would require the pool to override the return value of a method it
delegates to, creating a leaky abstraction. The connection should know its own limit.

### Decision 6: Per-connection health breakdown as a list

**Choice:** Extend `get_health_summary()` to include a `connections` key containing
a list of dicts, each with `label`, `state`, `protocol`, `active_streams`,
`max_streams`.

**Rationale:** Aggregate counts are insufficient for debugging the cascading freeze —
operators need to see which specific connections are saturated. The list is ordered
by creation (ordinal).

## Risks / Trade-offs

- **Default=5 may be too low for high-throughput providers** → Mitigation: override
  in YAML per provider. The field is per-provider, so only providers that need a
  higher value are affected.
- **Breaking config change** (`dedicated_http_client` removal) → Mitigation: all
  existing configs use `true` (the default). Operators simply remove the line from
  YAML. `extra="forbid"` on `ProviderConfig` will reject stale YAML with a clear
  validation error.
- **More TCP connections opened** → Mitigation: each connection has TLS/H2 handshake
  overhead, but this is preferable to minutes of frozen requests. The pool's
  `max_connections` limit (default 100) still applies.
- **Connection label ordinal is per-pool, not global** → Acceptable: each provider
  has its own pool (since `dedicated_http_client` is removed and all providers get
  dedicated clients), so ordinals are unique within a provider's pool.
