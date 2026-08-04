# Tasks: add-sticky-key-mode

All code, comments, and documentation written during implementation MUST be in English. Follow AGENTS.md paradigm: pyright strict on `src/core/` and `src/config/`, Google-style docstrings, absolute imports `from src.*`, Black formatting (88 chars, double quotes), ruff rules, `StrEnum`/`@unique` enums, frozen dataclasses for immutable DTOs.

## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b feature/add-sticky-key-mode`
- [x] 1.2 Verify all existing tests pass before starting: run the full test suite (`make test` and `make ci`)

## 2. Core Domain (pyright strict)

- [x] 2.1 Add `KeySelectionMode` StrEnum (`ROUND_ROBIN = "round_robin"`, `STICKY = "sticky"`) and `BreakerState` StrEnum (`CLOSED`, `OPEN`, `HALF_OPEN`) to `src/core/constants.py` with `@unique` and Google-style docstrings (design D10; specs: sticky-key-selection "Key selection mode is configurable per provider", gateway-circuit-breaker "Circuit breaker scope and lifecycle")
- [x] 2.2 Add `CircuitBreakerParams` frozen dataclass to `src/core/models.py` (fields mirroring `CircuitBreakerConfig`: window_size, error_rate_threshold, min_samples, open_duration_sec, backoff_factor, max_open_duration_sec, probe_successes_to_close) with `Fields:` docstring section (design D6)
- [x] 2.3 Create `src/core/breaker/__init__.py` and `src/core/breaker/circuit_breaker.py` with `KeyCircuitBreaker`: pure synchronous state machine modeled on `src/core/batching/adaptive.py` (constructor takes `CircuitBreakerParams`; count-based sliding window `collections.deque(maxlen=window_size)`; `record_result(ok, error_reason)` consuming final refined `ErrorReason` where only `is_retryable()` failures count as wave evidence; CLOSED→OPEN on `min_samples` + `error_rate_threshold`; `should_fail_fast()`, `begin_probe()`, `record_probe_success()`, `record_probe_failure()` driving HALF_OPEN recovery with exponential cooldown capped at `max_open_duration_sec`; public observability counters `opened_events`, `closed_events`, `reopened_events`, `fail_fast_events`) (design D6–D8; spec gateway-circuit-breaker all requirements)
- [x] 2.4 Verify `poetry run pyright` passes with the new `src/core/` modules under strict mode

## 3. Configuration Layer

- [x] 3.1 Add `KeySelectionConfig` (`mode: KeySelectionMode = ROUND_ROBIN`) and `CircuitBreakerConfig` (fields + defaults per design D10, model validator enforcing `min_samples <= window_size` and `max_open_duration_sec >= open_duration_sec`) to `src/config/schemas.py`; nest both into `GatewayPolicyConfig` (spec: gateway-circuit-breaker "Circuit breaker configuration schema")
- [x] 3.2 Extend the `RetryPolicyConfig`/provider validation: when `key_selection.mode == sticky` and `retry.enabled`, require `on_key_error.attempts > 0` (`on_server_error.attempts` alone does not satisfy) (design D5; spec sticky-key-selection "Config validation for sticky mode with retry")
- [x] 3.3 Add defaults for `key_selection` and `circuit_breaker` to the provider template in `src/config/defaults.py` (three-tier defaults)
- [x] 3.4 Add annotated `key_selection` and `circuit_breaker` blocks to `config/example_full_config.yaml` (document semantics: sticky per-worker, rotation triggers, breaker behavior; English comments)
- [x] 3.5 Verify `poetry run pyright` passes for `src/config/` strict mode

## 4. Gateway Service Layer

- [x] 4.1 Extend `GatewayCache` (`src/services/gateway/gateway_cache.py`): per-provider selection mode + sticky pointer dict `(key_id, key_value)`; sticky selection returns the pointer key without deque rotation; pointer establishment on first pick; pointer re-validation by `key_id` inside `refresh_key_pool()` (keep if present, clear if absent); pointer cleared in `remove_key_from_pool()` when it matches; rotation helper selecting a new key excluding a failed `key_id` (design D2–D3; specs: provider-key-pool MODIFIED requirement, sticky-key-selection pointer requirements)
- [x] 4.2 Implement sticky rotation-trigger policy in the gateway layer consuming the final refined `ErrorReason`: client errors → no rotation/no penalty; fatal + `OVERLOADED` → rotate + ban; `RATE_LIMITED` → rotate + ban; `is_server_error()` → rotate WITHOUT `_report_key_failure` and WITHOUT `remove_key_from_pool` (design D4; spec sticky-key-selection "Rotation triggers in sticky mode", transparent-gateway-routing "Server errors do not penalize keys in sticky mode")
- [x] 4.3 Wire sticky mode into `_handle_full_stream_request()` (`src/services/gateway/gateway_service.py`): sticky selection, rotate pointer per triggers on failure, no request retry, upstream error returned to client (design D11; spec sticky-key-selection "Full-stream path honors sticky mode")
- [x] 4.4 Wire sticky mode into `_handle_buffered_retryable_request()`: disable the same-key `on_server_error` branch; every rotation trigger adds the key to the exclude set, increments `key_error_attempts`, applies `on_key_error` backoff, retries the REQUEST with a NEW key; keep `asyncio.timeout(timeouts.total)` and the 504 structured body (design D5; specs: sticky-key-selection "Sticky retry loop rotates the key and retries the request", transparent-gateway-routing "Sticky retry semantics in the buffered path")
- [x] 4.5 Instantiate one `KeyCircuitBreaker` per provider (sticky mode + `circuit_breaker.enabled` only) in gateway app state; wire `record_result` after every upstream attempt; OPEN state: bypass retry loop (fail-fast, transparent upstream error forwarding), ban freeze for retryable errors (fatal still bans), release sticky pointer and fall back to round-robin; HALF_OPEN probes and recovery per design D7–D9 (spec gateway-circuit-breaker OPEN/HALF_OPEN requirements)
- [x] 4.6 Add metrics via `IMetricsCollector`: breaker transitions (opened/closed/reopened), fail-fast request count, rotations without ban; `llm_gateway_` prefix, provider label, multiprocess-compatible counters (design D12; spec gateway-circuit-breaker "Breaker observability")
- [x] 4.7 Verify round-robin default path is byte-for-byte unchanged: run existing gateway unit tests without config changes

## 5. Documentation

- [x] 5.1 Create `docs/STICKY_KEY_MODE.md`: mode semantics, per-worker behavior (workers = keys in simultaneous use sizing guidance), rotation-trigger table, penalty semantics vs round-robin, retry-loop adaptation, circuit breaker states and actions, configuration reference (English)
- [x] 5.2 Update `docs/ERRORS.md` with a cross-reference to sticky-mode penalty semantics (server errors rotate without ban in sticky mode)
- [x] 5.3 Reference the new doc from `AGENTS.md`-style doc index only if such an index exists in `docs/`; otherwise skip (skipped: no index file exists in `docs/`)

## 6. Testing

MANDATE: the main implementation agent orchestrates tests by delegating each group below to a dedicated @Mr.Tester subagent. With EVERY delegation the implementation agent MUST pass the four testing-paradigm documents — `TESTING.md`, `TESTING-RUN.md`, `TESTING-GUIDE.md`, `TESTING-GATEKEEPER.md` — and instruct the tester to comply fully (Golden Rule / CanonicalConfig zero hardcodes, unittest.mock only, G1–G6 group placement, gatekeeper script). Launch all group delegations IN PARALLEL (single message).

- [x] 6.1 Read `test-plan.md` Delegation Groups and Coverage Map sections
- [x] 6.2 Delegate group `breaker-core-unit` to @Mr.Tester (scope: `tests/unit/core/test_breaker.py`, `test_breaker_purity.py`, `test_breaker_params.py`; attach the four TESTING documents)
- [x] 6.3 Delegate group `sticky-cache-unit` to @Mr.Tester (scope: `tests/unit/services/test_gateway_cache_sticky.py` NEW, `tests/unit/services/test_gateway_cache.py` MODIFY; attach the four TESTING documents)
- [x] 6.4 Delegate group `gateway-handlers-unit` to @Mr.Tester (scope: `tests/unit/services/test_gateway_sticky_handlers.py` NEW, `test_gateway_core.py`, `test_gateway_transparent_routing.py`, `test_gateway_timeout.py` MODIFY; attach the four TESTING documents)
- [x] 6.5 Delegate group `config-schema-unit` to @Mr.Tester (scope: `tests/unit/config/test_key_selection_config.py`, `test_circuit_breaker_config.py` NEW, `test_gateway_config.py`, `test_defaults.py`, `test_schemas.py` MODIFY; attach the four TESTING documents)
- [x] 6.6 Delegate group `enums-models-unit` to @Mr.Tester (scope: `tests/unit/core/test_models_check_result.py` MODIFY; attach the four TESTING documents)
- [x] 6.7 Delegate group `obsolete-tests-cleanup` to @Mr.Tester (scope: `tests/unit/core/test_constants.py`, `tests/unit/config/test_cross_field_constraints.py`; task: DELETE obsolete circuit_breaker-absence assertions, ADD enum tests and the sticky retry-validation test per test-plan.md Test Modifications; attach the four TESTING documents)
- [x] 6.8 Review @Mr.Tester reports and fix any source-level bugs discovered (testers report bugs, they do not fix source)
- [x] 6.9 Re-delegate any groups affected by source fixes (again with the four TESTING documents attached) (not needed: no source bugs reported; gatekeeper violations in `test_gateway_sticky_handlers.py` were resolved by the owning group)
- [x] 6.10 Verify all groups pass and coverage matches `test-plan.md`

## 7. Quality Gates & Final Verification

- [x] 7.1 `poetry run pyright` — clean (strict on `src/core/`, `src/config/`)
- [x] 7.2 `poetry run ruff check src/ tests/` — clean
- [x] 7.3 `poetry run black --check src/ tests/` — clean
- [x] 7.4 `bash scripts/check-test-hardcodes.sh all` — exit code 0
- [x] 7.5 `make test` (G1–G5) — all pass; `make test-slow` unaffected
- [x] 7.6 `make ci` — full pipeline green
- [x] 7.7 Manual config smoke check: load `config/example_full_config.yaml`, confirm defaults produce round-robin behavior; confirm a sticky override parses and validates
- [x] 7.8 `openspec validate --change add-sticky-key-mode` — pass before archiving
