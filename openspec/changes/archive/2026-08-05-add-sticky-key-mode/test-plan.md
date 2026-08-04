# QA Strategy & Test Plan

## Coverage Map

### sticky-key-selection

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| sticky-key-selection | Key selection mode is configurable per provider | Default mode is round_robin | `tests/unit/config/test_key_selection_config.py` | `test_default_mode_is_round_robin` | config-schema-unit |
| sticky-key-selection | Key selection mode is configurable per provider | Per-provider override to sticky | `tests/unit/config/test_key_selection_config.py` | `test_per_provider_override_to_sticky` | config-schema-unit |
| sticky-key-selection | Key selection mode is configurable per provider | Invalid mode rejected at config load | `tests/unit/config/test_key_selection_config.py` | `test_invalid_mode_rejected_at_config_load` | config-schema-unit |
| sticky-key-selection | Sticky pointer is per-worker and in-memory | Two workers hold different sticky keys | `tests/unit/services/test_gateway_cache_sticky.py` | `test_two_workers_hold_different_sticky_keys` | sticky-cache-unit |
| sticky-key-selection | Sticky pointer is per-worker and in-memory | Worker restart resets the pointer | `tests/unit/services/test_gateway_cache_sticky.py` | `test_worker_restart_resets_pointer` | sticky-cache-unit |
| sticky-key-selection | Sticky selection returns the pointer key without rotating the pool | Consecutive requests reuse the same key | `tests/unit/services/test_gateway_cache_sticky.py` | `test_consecutive_requests_reuse_same_key` | sticky-cache-unit |
| sticky-key-selection | Sticky selection returns the pointer key without rotating the pool | Deque is not rotated by sticky selection | `tests/unit/services/test_gateway_cache_sticky.py` | `test_deque_not_rotated_by_sticky_selection` | sticky-cache-unit |
| sticky-key-selection | Sticky selection returns the pointer key without rotating the pool | First request establishes the pointer | `tests/unit/services/test_gateway_cache_sticky.py` | `test_first_request_establishes_pointer` | sticky-cache-unit |
| sticky-key-selection | Sticky pointer survives cache refresh | Pointer survives periodic refresh | `tests/unit/services/test_gateway_cache_sticky.py` | `test_pointer_survives_periodic_refresh` | sticky-cache-unit |
| sticky-key-selection | Sticky pointer survives cache refresh | Pointer cleared when key disappears from pool | `tests/unit/services/test_gateway_cache_sticky.py` | `test_pointer_cleared_when_key_disappears_from_pool` | sticky-cache-unit |
| sticky-key-selection | Rotation triggers in sticky mode | Client error keeps the sticky key | `tests/unit/services/test_gateway_cache_sticky.py` | `test_client_error_keeps_sticky_key` | sticky-cache-unit |
| sticky-key-selection | Rotation triggers in sticky mode | Fatal error rotates and bans | `tests/unit/services/test_gateway_cache_sticky.py` | `test_fatal_error_rotates_and_bans` | sticky-cache-unit |
| sticky-key-selection | Rotation triggers in sticky mode | Rate limit rotates and bans | `tests/unit/services/test_gateway_cache_sticky.py` | `test_rate_limit_rotates_and_bans` | sticky-cache-unit |
| sticky-key-selection | Rotation triggers in sticky mode | Server error rotates without ban | `tests/unit/services/test_gateway_cache_sticky.py` | `test_server_error_rotates_without_ban` | sticky-cache-unit |
| sticky-key-selection | Rotation re-establishes the pointer excluding the failed key | Rotation excludes the failed key | `tests/unit/services/test_gateway_cache_sticky.py` | `test_rotation_excludes_failed_key` | sticky-cache-unit |
| sticky-key-selection | Rotation re-establishes the pointer excluding the failed key | Pool exhausted during rotation | `tests/unit/services/test_gateway_cache_sticky.py` | `test_pool_exhausted_during_rotation` | sticky-cache-unit |
| sticky-key-selection | Direct removal of the sticky key clears the pointer | External removal clears matching pointer | `tests/unit/services/test_gateway_cache_sticky.py` | `test_external_removal_clears_matching_pointer` | sticky-cache-unit |
| sticky-key-selection | Full-stream path honors sticky mode | Full-stream error rotates pointer without retry | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_full_stream_error_rotates_pointer_without_retry` | gateway-handlers-unit |
| sticky-key-selection | Sticky retry loop rotates the key and retries the request | Server error rotates key instead of same-key retry | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_server_error_rotates_key_instead_of_same_key_retry` | gateway-handlers-unit |
| sticky-key-selection | Sticky retry loop rotates the key and retries the request | on_server_error config ignored in sticky mode | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_on_server_error_config_ignored_in_sticky_mode` | gateway-handlers-unit |
| sticky-key-selection | Sticky retry loop rotates the key and retries the request | Client error aborts without consuming counters | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_client_error_aborts_without_consuming_counters` | gateway-handlers-unit |
| sticky-key-selection | Config validation for sticky mode with retry | Sticky retry without key-error attempts rejected | `tests/unit/config/test_cross_field_constraints.py` | `test_sticky_retry_without_key_error_attempts_rejected` | obsolete-tests-cleanup |

### gateway-circuit-breaker

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| gateway-circuit-breaker | Circuit breaker scope and lifecycle | Breaker state is per-worker | `tests/unit/core/test_breaker.py` | `test_breaker_state_is_per_worker` | breaker-core-unit |
| gateway-circuit-breaker | Circuit breaker scope and lifecycle | Worker restart resets the breaker | `tests/unit/core/test_breaker.py` | `test_worker_restart_resets_breaker` | breaker-core-unit |
| gateway-circuit-breaker | Breaker is active only in sticky mode | Round-robin mode ignores the breaker | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_round_robin_mode_ignores_breaker` | gateway-handlers-unit |
| gateway-circuit-breaker | Breaker is active only in sticky mode | Breaker disabled in sticky mode | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_breaker_disabled_in_sticky_mode` | gateway-handlers-unit |
| gateway-circuit-breaker | Count-based sliding window | Window evicts oldest outcomes | `tests/unit/core/test_breaker.py` | `test_window_evicts_oldest_outcomes` | breaker-core-unit |
| gateway-circuit-breaker | Count-based sliding window | Fatal and client errors are not wave evidence | `tests/unit/core/test_breaker.py` | `test_fatal_and_client_errors_not_wave_evidence` | breaker-core-unit |
| gateway-circuit-breaker | Opening condition | Threshold reached opens the breaker | `tests/unit/core/test_breaker.py` | `test_threshold_reached_opens_breaker` | breaker-core-unit |
| gateway-circuit-breaker | Opening condition | Below min_samples the breaker stays closed | `tests/unit/core/test_breaker.py` | `test_below_min_samples_stays_closed` | breaker-core-unit |
| gateway-circuit-breaker | OPEN state fail-fast with transparent error forwarding | Fail-fast returns upstream error | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_fail_fast_returns_upstream_error` | gateway-handlers-unit |
| gateway-circuit-breaker | OPEN state ban freeze | Retryable failure during OPEN does not ban | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_retryable_failure_during_open_does_not_ban` | gateway-handlers-unit |
| gateway-circuit-breaker | OPEN state ban freeze | Fatal failure during OPEN still bans | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_fatal_failure_during_open_still_bans` | gateway-handlers-unit |
| gateway-circuit-breaker | OPEN state round-robin fallback | Probe traffic rotates keys | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_probe_traffic_rotates_keys` | gateway-handlers-unit |
| gateway-circuit-breaker | Cooldown and HALF_OPEN recovery | Successful probes close the breaker | `tests/unit/core/test_breaker.py` | `test_successful_probes_close_breaker` | breaker-core-unit |
| gateway-circuit-breaker | Cooldown and HALF_OPEN recovery | Failed probe re-opens with exponential cooldown | `tests/unit/core/test_breaker.py` | `test_failed_probe_reopens_with_exponential_cooldown` | breaker-core-unit |
| gateway-circuit-breaker | Cooldown and HALF_OPEN recovery | Cooldown capped at maximum | `tests/unit/core/test_breaker.py` | `test_cooldown_capped_at_maximum` | breaker-core-unit |
| gateway-circuit-breaker | Breaker observability | State transition increments counter | `tests/unit/core/test_breaker.py` | `test_state_transition_increments_counter` | breaker-core-unit |
| gateway-circuit-breaker | Breaker observability | Fail-fast requests counted | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_fail_fast_requests_counted` | gateway-handlers-unit |
| gateway-circuit-breaker | Circuit breaker configuration schema | Defaults applied when section omitted | `tests/unit/config/test_circuit_breaker_config.py` | `test_defaults_applied_when_section_omitted` | config-schema-unit |
| gateway-circuit-breaker | Circuit breaker configuration schema | Inconsistent window settings rejected | `tests/unit/config/test_circuit_breaker_config.py` | `test_inconsistent_window_settings_rejected` | config-schema-unit |

### provider-key-pool

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| provider-key-pool | get_key_from_pool accepts provider_name only | Key retrieved without model name in round-robin mode | `tests/unit/services/test_gateway_cache.py` | `test_get_key_from_pool_without_model_name` (existing, verified) | sticky-cache-unit |
| provider-key-pool | get_key_from_pool accepts provider_name only | Sticky mode returns pointer key without rotation | `tests/unit/services/test_gateway_cache_sticky.py` | `test_sticky_mode_returns_pointer_key_without_rotation` | sticky-cache-unit |
| provider-key-pool | get_key_from_pool accepts provider_name only | No valid keys available | `tests/unit/services/test_gateway_cache.py` | `test_get_key_from_pool_returns_none_when_empty` (existing, verified) | sticky-cache-unit |

### transparent-gateway-routing

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| transparent-gateway-routing | Both request paths honor the configured key selection mode | Sticky mode in full-stream path | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_sticky_mode_in_full_stream_path` | gateway-handlers-unit |
| transparent-gateway-routing | Both request paths honor the configured key selection mode | Sticky mode in buffered path | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_sticky_mode_in_buffered_path` | gateway-handlers-unit |
| transparent-gateway-routing | Both request paths honor the configured key selection mode | Dispatch unchanged by selection mode | `tests/unit/services/test_gateway_transparent_routing.py` | `test_dispatch_unchanged_by_selection_mode` | gateway-handlers-unit |
| transparent-gateway-routing | Sticky retry semantics in the buffered path | Retryable error consumes key-error attempts in sticky mode | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_retryable_error_consumes_key_error_attempts_in_sticky` | gateway-handlers-unit |
| transparent-gateway-routing | Sticky retry semantics in the buffered path | Total deadline still enforced in sticky mode | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_total_deadline_still_enforced_in_sticky_mode` | gateway-handlers-unit |
| transparent-gateway-routing | Server errors do not penalize keys in sticky mode | Server error in sticky full-stream path leaves key untouched | `tests/unit/services/test_gateway_sticky_handlers.py` | `test_server_error_in_full_stream_leaves_key_untouched` | gateway-handlers-unit |
| transparent-gateway-routing | Server errors do not penalize keys in sticky mode | Round-robin penalty behavior unchanged | `tests/unit/services/test_gateway_core.py` | `test_full_stream_skips_penalty_for_client_error` (existing, verified unchanged) | gateway-handlers-unit |

## Delegation Groups

### Group: breaker-core-unit
**Scope:** `tests/unit/core/test_breaker.py`, `tests/unit/core/test_breaker_purity.py`, `tests/unit/core/test_breaker_params.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/test_breaker.py` | 10 (breaker state per-worker, worker restart resets breaker, window evicts oldest outcomes, fatal/client errors not wave evidence, threshold opens breaker, below min_samples stays closed, successful probes close breaker, failed probe exponential cooldown, cooldown capped at max, state transition increments counter) | NEW |
| `tests/unit/core/test_breaker_purity.py` | 1 (purity — no config imports in src/core/breaker/, imports CircuitBreakerParams from core.models) | NEW |
| `tests/unit/core/test_breaker_params.py` | 1 (CircuitBreakerParams frozen dataclass construction and immutability) | NEW |

### Group: sticky-cache-unit
**Scope:** `tests/unit/services/test_gateway_cache.py`, `tests/unit/services/test_gateway_cache_sticky.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_cache_sticky.py` | 16 (two workers hold different keys, worker restart resets, consecutive requests reuse, deque not rotated, first request establishes, pointer survives refresh, pointer cleared on key disappearance, client error keeps key, fatal rotates+bans, rate limit rotates+bans, server error rotates without ban, rotation excludes failed, pool exhausted during rotation, external removal clears pointer, sticky mode returns pointer without rotation) | NEW |
| `tests/unit/services/test_gateway_cache.py` | 2 (get_key_from_pool without model_name, get_key_from_pool returns None when empty — both existing, verified unchanged) | MODIFY |

### Group: gateway-handlers-unit
**Scope:** `tests/unit/services/test_gateway_core.py`, `tests/unit/services/test_gateway_sticky_handlers.py`, `tests/unit/services/test_gateway_transparent_routing.py`, `tests/unit/services/test_gateway_timeout.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_sticky_handlers.py` | 16 (full-stream error rotates without retry, server error rotates key instead of same-key retry, on_server_error ignored in sticky, client error aborts without counters, round-robin ignores breaker, breaker disabled in sticky, fail-fast returns upstream error, retryable during OPEN no ban, fatal during OPEN still bans, probe traffic rotates keys, fail-fast counted, sticky in full-stream path, sticky in buffered path, retryable error consumes key-error attempts, total deadline enforced, server error full-stream leaves key untouched) | NEW |
| `tests/unit/services/test_gateway_core.py` | 1 (round-robin penalty behavior unchanged — existing test verified) | MODIFY |
| `tests/unit/services/test_gateway_transparent_routing.py` | 1 (dispatch unchanged by selection mode) | MODIFY |
| `tests/unit/services/test_gateway_timeout.py` | 1 (helper `_make_request_for_retry` extended for mode-awareness) | MODIFY |

### Group: config-schema-unit
**Scope:** `tests/unit/config/test_key_selection_config.py`, `tests/unit/config/test_circuit_breaker_config.py`, `tests/unit/config/test_gateway_config.py`, `tests/unit/config/test_defaults.py`, `tests/unit/config/test_schemas.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_key_selection_config.py` | 3 (default mode round_robin, per-provider override, invalid mode rejected) | NEW |
| `tests/unit/config/test_circuit_breaker_config.py` | 2 (defaults applied when omitted, inconsistent window settings rejected) | NEW |
| `tests/unit/config/test_gateway_config.py` | 0 (extend GatewayPolicyConfig tests for nested key_selection/circuit_breaker) | MODIFY |
| `tests/unit/config/test_defaults.py` | 0 (extend with CircuitBreaker defaults assertions) | MODIFY |
| `tests/unit/config/test_schemas.py` | 0 (validate KeySelectionConfig/CircuitBreakerConfig schemas directly) | MODIFY |

### Group: enums-models-unit
**Scope:** `tests/unit/core/test_models_check_result.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/test_models_check_result.py` | 0 (verify CircuitBreakerParams is importable from src.core.models) | MODIFY |

### Group: obsolete-tests-cleanup
**Scope:** `tests/unit/core/test_constants.py`, `tests/unit/config/test_cross_field_constraints.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/test_constants.py` | 2 (DELETE obsolete circuit_breaker-absence assertions; ADD KeySelectionMode + BreakerState enum membership/value tests) | MODIFY |
| `tests/unit/config/test_cross_field_constraints.py` | 1 (ADD `test_sticky_retry_without_key_error_attempts_rejected`; clarify comment on the server-attempts-only round-robin test) | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/unit/core/test_constants.py` | DELETE test `test_gateway_policy_config_has_no_circuit_breaker_field` | Circuit breaker field WILL exist in GatewayPolicyConfig (design D10). This negative assertion is the inverse of the new truth; the test is obsolete. |
| `tests/unit/core/test_constants.py` | DELETE test `test_defaults_have_no_circuit_breaker_key` | Defaults WILL include circuit_breaker section (design D10). This negative assertion is the inverse of the new truth; the test is obsolete. |
| `tests/unit/core/test_constants.py` | MODIFY — add `KeySelectionMode` and `BreakerState` enum tests | New enums introduced (design D10, proposal). Must verify StrEnum membership, @unique decorator, and values. |
| `tests/unit/config/test_cross_field_constraints.py` | MODIFY `test_retry_policy_enabled_with_only_server_attempts_passes` — add clarifying comment that this test covers the non-sticky (round_robin) case; behavior preserved | Design D5 changes the rule: in sticky mode, on_key_error.attempts must be >0 when retry.enabled. The existing test validates the non-sticky case which remains valid. A NEW test (`test_sticky_retry_without_key_error_attempts_rejected`) covers the sticky constraint. |
| `tests/unit/config/test_cross_field_constraints.py` | NEW test `test_sticky_retry_without_key_error_attempts_rejected` | Design D5 — sticky mode + retry.enabled + on_key_error.attempts=0 → ValidationError. Spec scenario: sticky-key-selection / Config validation for sticky mode with retry. |
| `tests/unit/services/test_gateway_cache.py` | MODIFY `TestGatewayCacheExcludeKeyIds` — add mode-aware fixture so tests pass with the new mode-dependent `get_key_from_pool` API | All existing tests operate in default round-robin mode; they should continue passing. The `GatewayCache` fixture may need a mode parameter or the test setup may need to explicitly set mode to `round_robin`. |
| `tests/unit/services/test_gateway_core.py` | MODIFY helper `_make_mock_request()` — set default `key_selection.mode` on the mock provider config to `round_robin` to ensure existing handler tests remain isolated | All existing handler tests assume round-robin. Adding explicit mode config in the mock prevents false failures when handlers consult the selection mode. |
| `tests/unit/services/test_gateway_core.py` | MODIFY `test_no_json_503_in_retry_handler` — update expected `JSONResponse(status_code=503)` count and `forward_error_to_client` call count for the sticky retry path | The static analysis counts may change if the sticky-mode path adds new JSONResponse(503) or forward_error_to_client calls. Run, observe, adjust the count. |
| `tests/unit/services/test_gateway_core.py` | MODIFY `test_upstream_attempt_used_in_all_handler_paths` — update expectations if sticky-mode handler paths introduce new forwarder calls | Same as above: static-analysis counts are brittle to handler code changes. |
| `tests/unit/services/test_gateway_transparent_routing.py` | MODIFY — add `test_dispatch_unchanged_by_selection_mode` | Verifies that switching between round_robin and sticky does not alter the full-stream vs buffered dispatch decision (transparent-gateway-routing spec scenario). |
| `tests/unit/services/test_gateway_timeout.py` | MODIFY helper `_make_request_for_retry()` — add optional `key_selection_mode` parameter to support sticky-mode timeout tests | Enables future sticky-mode timeout tests without breaking existing round-robin timeout tests. |

## Risks & Edge Cases

- **[Load concentrates on ≤ workers keys → per-key RPM/TPM hit faster]** → Covered by `test_rate_limit_rotates_and_bans` (sticky-cache-unit) verifying RATE_LIMITED triggers rotation+ban, and breaker tests (breaker-core-unit) verifying fail-fast during waves.
- **[Cross-worker divergence: worker B keeps a key worker A already rotated away from]** → Covered by `test_two_workers_hold_different_sticky_keys` (sticky-cache-unit) verifying independent per-worker state and `test_pointer_cleared_when_key_disappears_from_pool` verifying eventual consistency via cache refresh.
- **[Slow burn below breaker threshold]** → Covered by `test_server_error_rotates_without_ban` (sticky-cache-unit) verifying that Layer 1 (design D4) removes DB bans for server errors entirely, so sub-threshold noise only rotates in-request.
- **[Fail-fast surfaces upstream errors to clients during OPEN]** → Covered by `test_fail_fast_returns_upstream_error` (gateway-handlers-unit) verifying transparent forwarding of upstream error body without synthetic 503.
- **[Existing tests assert unconditional round-robin rotation or same-key server retries]** → Addressed by the obsolete-tests-cleanup group: all existing round-robin tests are preserved as-is; no existing test is deleted for being wrong — only the negative assertions about circuit_breaker absence are removed.
- **[Breaker state lost on worker restart]** → Covered by `test_worker_restart_resets_breaker` (breaker-core-unit) verifying CLOSED state + empty window on fresh start.
- **[STREAM_DISCONNECT mid-stream cannot be retried]** → Covered by `test_server_error_rotates_without_ban` (sticky-cache-unit, STREAM_DISCONNECT is `is_server_error()`) and `test_full_stream_error_rotates_pointer_without_retry` (gateway-handlers-unit, no request retry in full-stream path).
- **[Debug mode forces buffered path]** → Covered by `test_sticky_mode_in_buffered_path` (gateway-handlers-unit) and `test_dispatch_unchanged_by_selection_mode` verifying debug+sticky works through the buffered handler.
- **[Config validation edge cases: min_samples ≤ 0, error_rate_threshold = 0, backoff_factor < 1.0]** → Covered by `tests/unit/config/test_circuit_breaker_config.py` with Pydantic boundary tests for each field constraint (ge=1, gt=0, le=1, etc.).
- **[Round-robin backwards compatibility]** → Every existing round-robin test (G1, G3, G4) must continue to pass. The default mode `round_robin` preserves byte-for-byte identical behavior. The gatekeeper script (`bash scripts/check-test-hardcodes.sh all`) and `make ci` serve as the compatibility gate.

## Execution Order & Validation

1. **Implement** all NEW test files first (breaker-core-unit, sticky-cache-unit, gateway-handlers-unit, config-schema-unit new files).
2. **Apply** MODIFY changes to existing files (obsolete-tests-cleanup deletions, enum additions, helper updates).
3. **Run** `poetry run pyright` to verify strict-mode compliance on `src/core/breaker/`.
4. **Run** `bash scripts/check-test-hardcodes.sh all` — must pass with exit code 0 (Golden Rule).
5. **Run** `make test` — all G1–G5 groups must pass.
6. **Run** `make ci` — lint + typecheck + G1–G5 must pass; mirrors the CI pipeline.
