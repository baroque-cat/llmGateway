# Design: add-sticky-key-mode

## Context

The gateway selects API keys via `GatewayCache.get_key_from_pool()` — a `deque` per provider, `popleft()` + `append()` on every call (strict round-robin). Each of the N uvicorn workers (default 4) is a separate OS process with its own `GatewayCache`, its own asyncpg pool, and its own httpx clients; the only shared state is PostgreSQL. Every 10 seconds each worker atomically rebuilds its key pool from the DB (`refresh_key_pool()`, SQL without `ORDER BY`).

Error handling is classified by `ErrorReason` (single source of truth), optionally reclassified per provider by `error_parsing` rules; the final refined reason is the sole input to the gateway's penalty/retry decision tree. Today's retry loop (`_handle_buffered_retryable_request`) retries server errors with the SAME key (`on_server_error`, default 5 attempts), then bans and rotates; key errors rotate immediately (`on_key_error`, default 3 attempts). The full-stream path (`_handle_full_stream_request`) makes one attempt and penalizes the key on any non-client error.

Documented history (`docs/THROUGHPUT_BOTTLENECK_PROBLEM.md`) shows that penalizing keys for provider-infrastructure errors produces a cascading key burn: timeouts → penalties → rotation across the whole pool → total failure. Any "rotate only on error" mode must be protected against this.

Project precedent for self-tuning controllers: `AdaptiveBatchController` (`src/core/batching/adaptive.py`) — a synchronous pure controller in `core/` (pyright strict) driven by `ErrorReason` classification, with a frozen-dataclass params object in `core/models.py` and observability counters.

## Goals / Non-Goals

**Goals:**

- Optional per-provider sticky key selection: keep the same key across requests until a rotation trigger fires; default remains round-robin with byte-for-byte identical behavior.
- Sticky state is per-worker, survives the 10 s cache refresh, requires no cross-worker coordination and no DB changes.
- Sticky-specific penalty semantics that kill the cascade at the root: server errors rotate without ban.
- Retry adaptation in sticky mode: retry = change key + retry request; no same-key server retries.
- A circuit breaker (part of sticky mode) that stops retry storms and key burn during provider-wide failure waves, with transparent fail-fast and round-robin probe fallback.
- Full compliance with AGENTS.md: Pydantic v2 config with three-tier defaults, `StrEnum`s in `core/`, pure controller logic under pyright strict, Google-style docstrings, Golden-Rule tests.

**Non-Goals:**

- Global (cross-worker) stickiness, DB leases, Redis or any new shared-state mechanism.
- Session/client-affinity stickiness (per-client key binding). Sticky is per-worker, not per-client.
- Changing round-robin behavior, the 10 s refresh interval, or the `ORDER BY`-less pool query.
- Changing Keeper health-check logic or `error_parsing` rule mechanics.
- Time-based rotation ("change key every T seconds") or request-count rotation ("after N requests") — possible follow-ups, out of scope.

## Decisions

### D1. Stickiness is per-worker, in-memory only

Each worker keeps its own sticky pointer per provider. Up to `workers` distinct keys are in simultaneous use per provider.

- **Why:** matches the existing architecture (no shared state anywhere; bans already propagate via DB with up to 10 s staleness). Worker count becomes a sizing knob: want N keys in parallel → run ≥ N workers.
- **Alternatives rejected:** DB lease/lock for a single global key (DB traffic in the hot path, lock contention, complexity); Redis (new dependency, violates the deployment model).

### D2. Selection mode lives inside `GatewayCache` (no new interface)

`GatewayCache` gains a per-provider selection mode and a sticky-pointer dict. No `IKeySelector` abstraction.

- **Why:** the pointer must stay consistent with pool mutations (`remove_key_from_pool`, `refresh_key_pool`) that already happen under the cache's `_refresh_lock`. A separate strategy object would split state that must move atomically.
- **Alternative noted:** extract a Strategy (`IKeySelector`) if a third mode ever appears. Until then, indirection buys nothing.

### D3. Sticky pointer stores `key_id` + `key_value`, re-validated by `key_id` after refresh

After each `refresh_key_pool()` rebuild, the pointer is re-validated: if the `key_id` exists in the new pool, the pointer is kept (value refreshed from the pool); otherwise it is cleared and the next request re-establishes it from the pool head.

- **Why:** the pool is rebuilt atomically every 10 s; identity is the DB `key_id`, not position. This is the "survive cache rotation" requirement.

### D4. Sticky penalty semantics: server errors rotate without ban

Rotation triggers consume the final refined `ErrorReason`:

| Category | Sticky behavior |
| --- | --- |
| Client errors (`BAD_REQUEST`, `UNKNOWN`, incl. pool-saturation `LocalProtocolError`) | No rotation, no penalty |
| Fatal (`INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL`) + `OVERLOADED` | Rotate + ban (as today) |
| `RATE_LIMITED` | Rotate + ban (per-key quota exhausted) |
| `is_server_error()` (`SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT`) | Rotate key for the current request; **no DB ban, no pool removal** |

- **Why:** `is_server_error()` is documented as "provider's infrastructure, not with a specific API key" (`src/core/constants.py`). Banning keys for provider faults is the documented cascade mechanism. Rotation within a request still gives the request a fresh key; the pool survives the outage.
- **Alternatives rejected:** shorter cooldown for server errors (still burns the pool, slower); ban as today (cascade).
- **Scope:** sticky mode only. Round-robin keeps today's penalty logic unchanged.

### D5. Retry loop in sticky mode: single rotation counter

With `retry.enabled` and sticky mode: any rotation trigger (fatal, `OVERLOADED`, `RATE_LIMITED`, server errors) adds the key to the request-local exclude set, increments `key_error_attempts`, applies `on_key_error` backoff, and retries the REQUEST with a NEW key. The same-key `on_server_error` branch is not executed; `on_server_error` config is ignored. Client errors abort without consuming counters (unchanged). `asyncio.timeout(timeouts.total)` still wraps the loop.

- **Why:** user-defined semantics — "the key changes; the request is retried". One counter keeps the loop simple and predictable.
- **Config validation:** when sticky mode and `retry.enabled` are both set, `on_key_error.attempts` MUST be > 0 (the existing `RetryPolicyConfig` validator is extended; `on_server_error.attempts` no longer satisfies the requirement in sticky mode).

### D6. Circuit breaker: pure synchronous controller in `src/core/breaker/`

`KeyCircuitBreaker` mirrors the `AdaptiveBatchController` precedent: pure synchronous state machine in `core/` (pyright strict), params as `@dataclass(frozen=True)` (`CircuitBreakerParams`) in `core/models.py`, observability counters as public attributes, wiring in `services/gateway/`. One instance per provider per worker, owned by `GatewayCache`/gateway service state.

- **Window:** count-based sliding window (`collections.deque(maxlen=window_size)`) of recent upstream outcomes (success / retryable-error / other). No timers for the error-rate computation.
- **Opening condition (CLOSED → OPEN):** window has ≥ `min_samples` outcomes AND retryable-error share ≥ `error_rate_threshold`. Fatal and client errors do not count as wave evidence (fatal is key-specific; client is request-specific); they are recorded as non-error slots only insofar as they are not retryable.
- **Why count-based:** simpler, deterministic under tests, no background timers; approved decision.

### D7. OPEN-state actions

1. **Fail-fast:** the retry loop is bypassed — one upstream attempt; the upstream error is forwarded to the client transparently (no synthetic 503). Transparency chosen over masking.
2. **Ban freeze:** retryable errors (incl. `RATE_LIMITED`) do NOT trigger `_report_key_failure` or `remove_key_from_pool` while OPEN. Fatal errors still ban (a dead key is dead regardless of the wave).
3. **Round-robin fallback:** the sticky pointer is released; selection reverts to round-robin so probe traffic spreads across keys instead of hammering one.

### D8. HALF_OPEN recovery with exponential cooldown

After `open_duration_sec` elapses, the breaker enters HALF_OPEN: requests flow as probes (round-robin selection). `probe_successes_to_close` consecutive successes → CLOSED, sticky re-engages (pointer binds to the last successful key). Any retryable failure → back to OPEN with `open_duration ×= backoff_factor`, capped at `max_open_duration_sec`. Cooldown success resets the duration to base.

- **Why:** mirrors `AdaptiveBatchController`'s aggressive-backoff/gradual-recovery philosophy; prevents flapping.

### D9. Breaker is gated by sticky mode

The breaker is active only when `key_selection.mode == sticky` AND `circuit_breaker.enabled`. In round-robin mode the breaker object is never consulted. This keeps the round-robin path untouched and makes the breaker part of the sticky feature, as decided.

### D10. Configuration surface

```yaml
gateway_policy:
  key_selection:
    mode: round_robin        # round_robin (default) | sticky
  circuit_breaker:
    enabled: true            # consulted only in sticky mode
    window_size: 20          # count-based sliding window, ge=1
    error_rate_threshold: 0.5  # (0, 1]
    min_samples: 5           # ge=1, le=window_size (validator)
    open_duration_sec: 30.0  # gt=0
    backoff_factor: 2.0      # ge=1.0
    max_open_duration_sec: 300.0  # gt=0, validator: >= open_duration_sec
    probe_successes_to_close: 3   # ge=1
```

New Pydantic models `KeySelectionConfig` and `CircuitBreakerConfig` nested into `GatewayPolicyConfig` (`src/config/schemas.py`); defaults in `src/config/defaults.py` provider template; annotated example blocks in `config/example_full_config.yaml`. New enums `KeySelectionMode` and `BreakerState` (`StrEnum`, `@unique`) in `src/core/constants.py`.

### D11. Full-stream path honors sticky

With retry disabled, `_handle_full_stream_request` selects via the sticky pointer; on a rotation trigger it rotates the pointer per D4 and returns the upstream error to the client (no request retry — retry is disabled). Server errors do not penalize the key per D4.

### D12. Observability

New counters via `IMetricsCollector` (Prometheus single/multiprocess + in-memory backends), `llm_gateway_*` prefix, provider label: breaker state transitions (opened/closed/reopened), requests failed-fast, key rotations without ban. Follows existing metric registration patterns; multiprocess-safe (counters only).

## Risks / Trade-offs

- **[Load concentrates on ≤ workers keys → per-key RPM/TPM hit faster]** → `RATE_LIMITED` is a rotation trigger with ban; breaker absorbs waves; sizing guidance documented ("workers ≈ desired parallel keys").
- **[Cross-worker divergence: worker B keeps a key worker A already rotated away from]** → accepted eventual consistency, identical to today's ban propagation (≤ 10 s refresh window); documented in the spec and docs.
- **[Slow burn below breaker threshold]** → Layer 1 (D4) removes DB bans for server errors entirely, so below-threshold noise cannot drain the pool; only in-request rotation occurs.
- **[Fail-fast surfaces upstream errors to clients during OPEN]** → intended trade-off: stops the retry storm that deepens provider overload; transparent error forwarding preserves the proxy contract; documented.
- **[Existing tests assert unconditional round-robin rotation or same-key server retries]** → test plan MUST identify and remove/update obsolete tests (explicit deliverable), gatekeeper + `make test` enforce the rest.
- **[Breaker state lost on worker restart]** → intended: fresh workers start CLOSED; the window refills within `min_samples` requests.
- **[STREAM_DISCONNECT mid-stream cannot be retried]** → unchanged: bytes already sent; in sticky mode it rotates the pointer for subsequent requests without ban (it is `is_server_error()`).
- **[Debug mode forces buffered path]** → no conflict: sticky selection is used by both handlers; debug + sticky works through the buffered handler.

## Migration Plan

1. Ship with defaults `mode: round_robin`, breaker inactive → zero behavior change on deploy.
2. Enable per provider: set `gateway_policy.key_selection.mode: sticky` (optionally tune `circuit_breaker`), restart gateway workers.
3. Observe new metrics (breaker transitions, fail-fast count) and logs.
4. Rollback: remove/override the config block back to `round_robin`, restart. No DB migration, no data cleanup — breaker state is in-memory.

## Open Questions

None blocking. Metric names are finalized during implementation following the existing `llm_gateway_*` registry conventions.
