# Proposal: add-sticky-key-mode

## Why

The gateway rotates API keys round-robin on **every** request (`GatewayCache.get_key_from_pool()` pops and re-appends the deque head per call). This defeats provider-side prompt caching and session affinity, and spreads load thinly across all keys instead of fully utilizing one key's quota before moving on. Providers that offer caching benefits require the same key to be reused across consecutive requests.

Additionally, the naive "rotate only on error" semantics carry a documented cascade risk: under provider-wide overload, retryable errors (TIMEOUT/SERVER_ERROR/RATE_LIMITED) are not key-specific, yet rotating-and-banning on each failure burns the whole pool in seconds (the failure mode documented in `docs/THROUGHPUT_BOTTLENECK_PROBLEM.md`). A protective circuit breaker is required as part of the new mode.

## What Changes

- **New optional per-provider key selection mode** under `gateway_policy.key_selection.mode`: `round_robin` (default — current behavior fully preserved) or `sticky`.
- **Sticky semantics (per-worker)**: each uvicorn worker keeps its own sticky key pointer per provider. The pointer MUST survive the periodic (10 s) key-pool cache refresh by re-validating the stored `key_id` against the rebuilt pool. No cross-worker coordination; no new shared state.
- **Rotation triggers in sticky mode** (consume the final refined `ErrorReason` — `error_parsing` output — as the single source of truth):
  - Client errors (`BAD_REQUEST`, `UNKNOWN`, incl. pool-saturation `LocalProtocolError`): no rotation, no penalty.
  - Fatal errors (`INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL`) and `OVERLOADED`: rotate + ban (as today).
  - `RATE_LIMITED`: rotate + ban (per-key quota exhausted).
  - Server errors (`is_server_error()`: `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT`): rotate key for the current request, but **no DB ban and no pool removal** — the provider, not the key, is at fault. This applies only in sticky mode; round-robin keeps today's penalty logic unchanged.
- **Retry behavior in sticky mode**: same-key retry on server errors is disabled. Retry means *change key, retry the request* (the existing `on_key_error` mechanics). The `on_server_error` retry branch is ignored when sticky mode is active.
- **Circuit breaker (part of sticky mode)**: per-provider, per-worker, in-memory state machine (CLOSED → OPEN → HALF_OPEN). Count-based sliding window over the last N upstream results (no timers). When the share of retryable/server errors exceeds the threshold, the breaker opens and: (1) fail-fast — retry is temporarily disabled, the upstream error is returned to the client transparently; (2) ban freeze — retryable errors do not trigger `_report_key_failure`; (3) temporary fallback to round-robin selection for probe traffic. Half-open probes restore sticky mode after M consecutive successes; failures re-open with exponentially growing cooldown (capped).
- **Configuration**: new Pydantic v2 schemas (`KeySelectionConfig`, `CircuitBreakerConfig`) nested in `GatewayPolicyConfig`; three-tier defaults; annotated entries in `config/example_full_config.yaml`.
- **Enums**: new `KeySelectionMode` and `BreakerState` (`StrEnum`, `@unique`) in `src/core/constants.py`.
- **Metrics**: breaker state transitions, fail-fast request count, ban-free rotations (via existing `IMetricsCollector`, multiprocess-compatible).
- **Documentation**: new `docs/STICKY_KEY_MODE.md`; updates to `config/example_full_config.yaml` comments and `docs/ERRORS.md` cross-references.

## Capabilities

### New Capabilities

- `sticky-key-selection`: per-worker sticky key pointer, cache-refresh survival, rotation-trigger classification, sticky-specific penalty semantics (server errors rotate without ban), retry-loop adaptation (request retries on a new key, no same-key server retries), full-stream path support.
- `gateway-circuit-breaker`: CLOSED/OPEN/HALF_OPEN state machine driven by a count-based sliding window; fail-fast with transparent upstream-error forwarding; ban freeze while open; temporary round-robin fallback; exponential cooldown backoff with cap; recovery probes; observability counters.

### Modified Capabilities

- `provider-key-pool`: the spec currently mandates round-robin rotation on every `get_key_from_pool()` call. Requirements change to make the selection policy mode-dependent: round-robin remains the default and MUST stay byte-for-byte compatible; sticky mode selects via the per-worker pointer without rotating the deque.
- `transparent-gateway-routing`: handler dispatch requirements extend so that both the full-stream and buffered-retryable paths honor the configured selection mode; in sticky mode the retry loop ignores the `on_server_error` same-key branch and rotates the key instead; server-error penalties are suppressed per sticky semantics.

## Impact

- **Code**: `src/core/constants.py` (new enums), `src/core/models.py` (breaker params dataclass), new `src/core/breaker/` (pure state-machine controller, pyright-strict, modeled on `src/core/batching/adaptive.py`), `src/config/schemas.py` + `src/config/defaults.py` (new config), `src/services/gateway/gateway_cache.py` (selection policy + sticky pointer), `src/services/gateway/gateway_service.py` (both request handlers + breaker wiring), `src/metrics/` (new counters).
- **Config artifacts**: `config/example_full_config.yaml` (annotated `key_selection` + `circuit_breaker` blocks).
- **Docs**: new `docs/STICKY_KEY_MODE.md`; comment updates in example config.
- **Tests**: new unit tests for the breaker state machine (`tests/unit/core/`), selection policy and sticky pointer (`tests/unit/services/`), config schema tests (`tests/unit/config/`); identification and removal of tests that assert unconditional round-robin rotation or same-key server retries as the only behavior; all tests comply with the Golden Rule (`CanonicalConfig`, zero hardcodes).
- **No database changes**: breaker state is in-memory per worker; no new tables or migrations.
- **Backwards compatibility**: default configuration produces identical behavior to today; no changes to public provider interfaces (`IProvider` unchanged).
