# Sticky Key Mode

This document describes the optional **sticky** key selection mode for the
Conductor (API Gateway), the associated penalty semantics, and the built-in
**circuit breaker** that protects the key pool during provider-wide failure
waves.

Default behavior is unchanged: every provider starts in `round_robin` mode
with the circuit breaker inactive. Sticky mode is opt-in per provider.

---

## 1. Why Sticky Mode

Round-robin rotation picks a different API key for **every** request. This:

- defeats provider-side prompt caching and session affinity, which require the
  same key across consecutive requests;
- spreads load thinly across all keys instead of fully utilizing one key's
  quota before moving on.

Sticky mode keeps the **same key** for consecutive requests and rotates only
when a rotation trigger fires (see Section 4).

## 2. Per-Worker Behavior

Sticky state is **per uvicorn worker process** and in-memory only:

- Each worker maintains its own sticky key pointer per provider instance.
- The pointer is **not** persisted to the database and **not** shared between
  workers; up to `workers` distinct keys can be in simultaneous use per
  provider.
- A worker restart resets all of its sticky pointers; the next request
  re-establishes the pointer from the pool head.

**Sizing guidance:** the worker count is the knob for parallel key usage.
Want N keys used in parallel for a provider → run at least N workers.

Cross-worker divergence is accepted eventual consistency (identical to how DB
bans propagate with up to the 10-second cache-refresh staleness): worker B may
keep a key that worker A already rotated away from until its next pool
refresh.

### Pointer lifecycle

- **Establishment:** when the pointer is unset, the next request takes a key
  from the pool (round-robin scan, honoring the request-local exclude set) and
  binds the pointer to it.
- **Selection:** while the pointer is set and its `key_id` is present in the
  pool, selection returns the pointer's `(key_id, key_value)` **without
  rotating the deque**.
- **Cache refresh survival:** after each periodic (10 s) `refresh_key_pool()`
  rebuild, the pointer is re-validated by `key_id` against the new pool. If
  present, the pointer is kept (value refreshed from the new pool); if absent
  (banned by Keeper, removed from config), the pointer is cleared and the next
  request re-establishes it.
- **Direct removal:** `remove_key_from_pool()` clears the pointer when it
  holds the removed key.
- **Rotation:** on a rotation trigger, a new key is selected from the pool
  **excluding the failed `key_id`** and becomes the new pointer. If no other
  key is available, selection returns `None` and the gateway responds with the
  standard no-available-keys error.

## 3. Configuration

```yaml
providers:
  - instance_name: deepseek-main
    gateway_policy:
      key_selection:
        mode: sticky            # round_robin (default) | sticky
      circuit_breaker:
        enabled: true           # consulted only in sticky mode
        window_size: 20         # count-based sliding window, >= 1
        error_rate_threshold: 0.5   # retryable-error share in (0, 1]
        min_samples: 5          # >= 1, must be <= window_size
        open_duration_sec: 30.0 # base cooldown, > 0
        backoff_factor: 2.0     # cooldown multiplier, >= 1.0
        max_open_duration_sec: 300.0  # cooldown cap, >= open_duration_sec
        probe_successes_to_close: 3   # consecutive HALF_OPEN successes, >= 1
```

- The mode is overridable per provider instance; providers without the
  section get `round_robin` defaults.
- **Validation:** when `mode: sticky` and `retry.enabled: true`,
  `retry.on_key_error.attempts` must be `>= 1`. The `on_server_error` attempts
  do not satisfy this requirement in sticky mode (the same-key server retry
  branch is never executed).
- The circuit breaker is active only when `mode: sticky` **and**
  `circuit_breaker.enabled`. In `round_robin` mode the breaker is never
  consulted regardless of its configuration.

## 4. Rotation Triggers and Penalty Semantics

Rotation decisions consume the **final refined `ErrorReason`** (after
`error_parsing` reclassification) as the single source of truth.

| Category | Reasons | Sticky behavior |
| :--- | :--- | :--- |
| Client errors | `BAD_REQUEST`, `UNKNOWN` (incl. pool-saturation `LocalProtocolError`) | No rotation, no penalty |
| Fatal errors | `INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL` | Rotate + ban (`_report_key_failure` + pool removal) |
| `OVERLOADED` | `OVERLOADED` | Rotate + ban |
| `RATE_LIMITED` | `RATE_LIMITED` | Rotate + ban (per-key quota exhausted) |
| Server errors | `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT` (`is_server_error()`) | Rotate key for the current request; **no DB ban, no pool removal** |

**Why server errors rotate without ban:** `is_server_error()` classifies
provider-infrastructure faults, not key faults. Banning keys for provider
outages is the documented cascade mechanism
(`docs/THROUGHPUT_BOTTLENECK_PROBLEM.md`, `docs/CASCADING_FREEZE_EVIDENCE.md`):
timeouts → penalties → rotation across the whole pool → total key burn.
Sticky mode kills the cascade at the root: the request still gets a fresh key,
but the pool survives the outage.

Round-robin mode keeps the existing penalty behavior unchanged. See
`docs/ERRORS.md` for the full `ErrorReason` classification.

## 5. Retry Loop Adaptation

With `retry.enabled` and sticky mode active, `_handle_buffered_retryable_request()`:

- **never** executes the same-key `on_server_error` retry branch; the
  `on_server_error` configuration is ignored;
- on **any** rotation trigger (fatal, `OVERLOADED`, `RATE_LIMITED`, server
  errors): adds the failed key to the request-local exclude set, increments
  `key_error_attempts`, applies the `on_key_error` backoff
  (`backoff_sec * backoff_factor ** (attempts - 1)`), and retries the
  **request with a new key**;
- on client errors: aborts without consuming counters and without changing the
  sticky pointer (unchanged semantics);
- still wraps the loop in `asyncio.timeout(timeouts.total)` and returns the
  structured `504 Gateway Timeout` body on deadline exhaustion.

With `retry.enabled: false`, `_handle_full_stream_request()` selects via the
sticky pointer, applies the rotation triggers on failure (rotating the pointer
for subsequent requests), and returns the upstream error to the client — no
request retry occurs.

Dispatch between the full-stream and buffered handlers is determined solely by
`debug_mode` and `retry.enabled`; the selection mode never changes dispatch.

## 6. Circuit Breaker

One `KeyCircuitBreaker` instance exists per provider per worker (pure
synchronous state machine in `src/core/breaker/`, no timers, no DB state).
States: `CLOSED` → `OPEN` → `HALF_OPEN`.

### CLOSED (normal operation)

- A count-based sliding window of the last `window_size` upstream outcomes is
  maintained (`collections.deque(maxlen=window_size)`).
- Only failures whose reason `is_retryable()` count as wave evidence;
  successes and non-retryable failures (fatal, client) occupy window slots but
  do not count toward the error share.
- **Opening condition:** the window holds at least `min_samples` outcomes AND
  the retryable-error share is `>= error_rate_threshold` → transition to
  `OPEN`.

### OPEN (fail-fast protection)

1. **Fail-fast:** the retry loop is bypassed — exactly one upstream attempt;
   on failure the upstream error is forwarded to the client **transparently**
   (no synthetic `503` or gateway-generated body).
2. **Ban freeze:** retryable errors (including `RATE_LIMITED`) do **not**
   trigger `_report_key_failure` or pool removal while OPEN. Fatal errors
   still ban and remove the key (a dead key is dead regardless of the wave).
3. **Round-robin fallback:** the sticky pointer is released; selection reverts
   to round-robin so probe traffic spreads across the pool instead of
   hammering one key.

After `open_duration_sec` (the current cooldown) elapses, the breaker
transitions to `HALF_OPEN`.

### HALF_OPEN (recovery probes)

- Requests flow as probes with round-robin selection.
- `probe_successes_to_close` **consecutive** successful upstream attempts →
  transition to `CLOSED`: sticky selection re-engages and the pointer binds to
  the last successful probe key; the cooldown resets to the base
  `open_duration_sec`; the window is cleared.
- Any retryable failure → back to `OPEN` with the cooldown multiplied by
  `backoff_factor`, capped at `max_open_duration_sec` (exponential backoff
  prevents flapping during prolonged outages).

Worker restart resets the breaker to `CLOSED` with an empty window; the window
refills within `min_samples` requests.

## 7. Observability

New `llm_gateway_*` counters (provider label, multiprocess-compatible):

| Metric | Meaning |
| :--- | :--- |
| `llm_gateway_breaker_opened_total` | CLOSED → OPEN transitions |
| `llm_gateway_breaker_closed_total` | HALF_OPEN → CLOSED recoveries |
| `llm_gateway_breaker_reopened_total` | HALF_OPEN → OPEN re-openings |
| `llm_gateway_breaker_fail_fast_requests_total` | Requests served fail-fast while OPEN |
| `llm_gateway_sticky_rotations_without_ban_total` | Key rotations performed without DB ban (server errors) |

## 8. Migration and Rollback

1. Ship with defaults (`mode: round_robin`, breaker inactive) → zero behavior
   change on deploy.
2. Enable per provider: set `gateway_policy.key_selection.mode: sticky`
   (optionally tune `circuit_breaker`), restart gateway workers.
3. Observe the new metrics and logs.
4. Rollback: set the mode back to `round_robin` and restart. No DB migration,
   no data cleanup — breaker state and sticky pointers are in-memory.
