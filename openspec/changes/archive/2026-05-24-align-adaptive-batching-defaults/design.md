## Context

The llmGateway configuration system uses three tiers of defaults:
1. `src/config/defaults.py` — hardcoded base dictionary
2. User YAML (deep-merged on top of Tier 1)
3. Pydantic `Field(default=…)` — applied during `Config.model_validate()`

An audit revealed that `AdaptiveBatchingConfig.start_batch_size` and `start_batch_delay_sec` have divergent values across the tiers. Tier 1 (`defaults.py`) and the canonical example config both use `start_batch_size=10, start_batch_delay_sec=30.0`. Tier 3 (Pydantic) uses `start_batch_size=30, start_batch_delay_sec=15.0`.

The current upstream consumers of these values are:
- `AdaptiveBatchConfig.to_params()` → `AdaptiveBatchingParams` dataclass → `AdaptiveBatchController` in `src/core/batching/`
- `_process_provider_batch()` in key probes reads health policy config to create controllers
- The `@model_validator check_bounds` in `AdaptiveBatchingConfig` validates `start ∈ [min, max]`

## Goals / Non-Goals

**Goals:**
- Align Pydantic `Field(default=…)` values in `AdaptiveBatchingConfig` to match Tier 1 (`defaults.py`) and the example config
- Update all test assertions that hardcode the old defaults
- Ensure `check_bounds` validator still passes with the new values

**Non-Goals:**
- No changes to `defaults.py` or `example_full_config.yaml` (they are already correct)
- No changes to the loader (`loader.py`) or the deepmerge logic
- No changes to `AdaptiveBatchingParams` dataclass or `AdaptiveBatchController`
- No behavioral changes to the batching algorithm

## Decisions

**Decision 1: Fix Pydantic defaults, not `defaults.py`**

The values `10`/`30.0` appear in both `defaults.py` AND `example_full_config.yaml` — two sources agreeing versus one (Pydantic). The `10`/`30.0` pair was the intended canonical default (the example config serves as the authoritative reference for operators). Changing Pydantic to match preserves the existing behavior for all users who follow the documented setup flow (copy `example_full_config.yaml` → edit).

**Decision 2: Update test helper signature defaults**

`_default_policy()` in `tests/test_batching/test_probe_adaptive_integration.py` and `_make_adaptive_config` in `tests/test_batching/test_adaptive_security.py` have their own default parameter values (`start_batch_size=30, start_batch_delay_sec=15.0`). These are convenience defaults, not assertions against Pydantic. However, for consistency and to avoid future confusion, update them to `10`/`30.0`. Call sites that rely on distinct values for comparative testing (e.g., `test_ic16_multiple_providers_separate_controllers` at line 766-769) must keep their explicit argument overrides intact.

**Decision 3: No migration path needed**

This is a values-only change. No config files, schemas, or APIs change shape. Users already got the intended values through the deepmerge path (Tier 1 + Tier 2). The fix only affects users who created `HealthPolicyConfig()` directly without any YAML/`defaults.py` layer — which only happens in tests.

## Risks / Trade-offs

- **[Risk] A test written against the old Pydantic defaults outside the known 4 files** → Mitigation: full test suite run (`pytest`) after changes. Grep for `start_batch_size.*30` and `start_batch_delay_sec.*15` confirms all sites are accounted for.
- **[Risk] `check_bounds` validator rejection** → Mitigation: verified — `10 ∈ [5, 50]` and `30.0 ∈ [3.0, 120.0]`, both pass. The validator is not changed.
