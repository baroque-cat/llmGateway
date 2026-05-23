# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| config-consistency | AdaptiveBatchingConfig default values are consistent across config tiers | Pydantic default matches defaults.py | tests/test_batching/test_adaptive_batching_config.py | test_uc33_valid_config_with_defaults | batching-unit |
| config-consistency | AdaptiveBatchingConfig default values are consistent across config tiers | Pydantic default matches defaults.py | tests/unit/config/test_adaptive_batching_config_to_params.py | test_to_params_with_default_values | config-unit |
| config-consistency | AdaptiveBatchingConfig default values are consistent across config tiers | Pydantic default matches example_full_config.yaml | tests/unit/config/test_loader.py | test_load_yaml_with_explicit_adaptive_batching_values | config-unit |
| config-consistency | HealthPolicyConfig default factory produces consistent AdaptiveBatchingConfig | HealthPolicyConfig without explicit adaptive_batching | tests/unit/config/test_validator.py | test_ut_b04_health_policy_adaptive_batching_default_factory | config-unit |
| config-consistency | HealthPolicyConfig default factory produces consistent AdaptiveBatchingConfig | HealthPolicyConfig without explicit adaptive_batching | tests/test_batching/test_adaptive_batching_config.py | test_uc38_default_factory_populated_in_health_policy | batching-unit |
| config-consistency | HealthPolicyConfig default factory produces consistent AdaptiveBatchingConfig | HealthPolicyConfig without explicit adaptive_batching | tests/unit/core/test_probes_dispatcher.py | test_ut_h11_health_policy_config_without_batch_fields | core-unit |
| config-consistency | HealthPolicyConfig default factory produces consistent AdaptiveBatchingConfig | HealthPolicyConfig without explicit adaptive_batching | tests/test_batching/test_probe_adaptive_integration.py | test_ic11_adaptive_batching_absent_uses_default_factory | batching-unit |
| config-consistency | Bounds validator accepts new default values | New defaults pass bounds validation | tests/test_batching/test_adaptive_batching_config.py | test_ut_a06_start_batch_size_within_bounds_valid | batching-unit |
| config-consistency | Bounds validator accepts new default values | New defaults pass bounds validation | tests/test_batching/test_adaptive_batching_config.py | test_ut_a07_start_batch_delay_within_bounds_valid | batching-unit |

## Delegation Groups

### Group: config-unit

**Scope:** tests/unit/config/

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/config/test_validator.py | 1 | MODIFY |
| tests/unit/config/test_adaptive_batching_config_to_params.py | 1 | MODIFY |
| tests/unit/config/test_loader.py | 1 | NEW |

### Group: core-unit

**Scope:** tests/unit/core/

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/core/test_probes_dispatcher.py | 1 | MODIFY |

### Group: batching-unit

**Scope:** tests/test_batching/

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_batching/test_adaptive_batching_config.py | 4 | MODIFY |
| tests/test_batching/test_adaptive_controller.py | 0 | MODIFY |
| tests/test_batching/test_adaptive_security.py | 0 | MODIFY |
| tests/test_batching/test_probe_adaptive_integration.py | 1 | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| tests/unit/config/test_validator.py | Docstring (lines 265-266): `start_batch_size=30` → `start_batch_size=10`, `start_batch_delay_sec=15.0` → `start_batch_delay_sec=30.0`; Assertions (lines 271-272): `== 30` → `== 10`, `== 15.0` → `== 30.0` | Scenario: HealthPolicyConfig without explicit adaptive_batching. Pydantic Field(default=30) and Field(default=15.0) are being changed to 10 and 30.0 respectively. |
| tests/unit/core/test_probes_dispatcher.py | Assertions (lines 347-348): `== 30` → `== 10`, `== 15.0` → `== 30.0` | Scenario: HealthPolicyConfig without explicit adaptive_batching. Same Pydantic default change. |
| tests/test_batching/test_probe_adaptive_integration.py | Helper `_default_policy` signature defaults (lines 85-86): `int = 30` → `int = 10`, `float = 15.0` → `float = 30.0`; Docstring (line 594): `start_batch_size=30, start_batch_delay_sec=15.0` → `start_batch_size=10, start_batch_delay_sec=30.0`; Comment (line 609): `# start_batch_size=30, start_batch_delay_sec=15.0` → `# start_batch_size=10, start_batch_delay_sec=30.0`; Assertions (lines 612-613): `== 30` → `== 10`, `== 15.0` → `== 30.0`; Ramp-up comment + assertions (lines 617-620): `batch_size: 30 + 5 = 35` → `batch_size: 10 + 5 = 15`, `== 35` → `== 15`, `batch_delay: 15.0 - 2.0 = 13.0` → `batch_delay: 30.0 - 2.0 = 28.0`, `== 13.0` → `== 28.0` | Decision 2: Helper convenience defaults must match new canonical values. Ramp-up assertions depend on starting controller state set by helper defaults. |
| tests/test_batching/test_adaptive_security.py | Helper `_make_config` signature defaults (lines 25-26): `int = 30` → `int = 10`, `float = 15.0` → `float = 30.0`; Helper `_make_controller` signature defaults (lines 58-59): `int = 30` → `int = 10`, `float = 15.0` → `float = 30.0` | Decision 2: Helper convenience defaults must match new canonical values. No test assertions change because all call sites use explicit arguments. |
| tests/test_batching/test_adaptive_controller.py | Helper `_make_controller` signature defaults (lines 50-51): `int = 30` → `int = 10`, `float = 15.0` → `float = 30.0`; `test_uc01` docstring (lines 70-71): `start_batch_size=30, start_batch_delay_sec=15.0` → `start_batch_size=10, start_batch_delay_sec=30.0`; `test_ut_d05` function name and docstring (lines 778-781): update to reflect new defaults `batch_size_10_delay_30`; `test_ut_d05` assertions (lines 786-787): `== 30` → `== 10`, `== 15.0` → `== 30.0`; `test_ut_d06_ramp_up` assertions (lines 797-798): `== 35` → `== 15` (comment: `# 30 + 5` → `# 10 + 5`), `== 13.0` → `== 28.0` (comment: `# 15 - 2.0` → `# 30.0 - 2.0`) | Decision 2 extended: Helper convenience defaults must match new canonical values. `test_ut_d05` and `test_ut_d06` use `AdaptiveBatchingConfig()` (no args) and `_make_controller()` (no args), respectively, so their assertions depend on the Pydantic/helper defaults. |
| tests/test_batching/test_adaptive_batching_config.py | `test_ut_a06` docstring (line 104): `start_batch_size=30` → `start_batch_size=10`, assignment (line 106): `start_batch_size=30` → `start_batch_size=10`, assertion (line 107): `== 30` → `== 10`; `test_ut_a07` docstring (line 117): `start_batch_delay_sec=15.0` → `start_batch_delay_sec=30.0`, assignment (line 119): `start_batch_delay_sec=15.0` → `start_batch_delay_sec=30.0`, assertion (line 120): `== 15.0` → `== 30.0`; `test_uc33` docstring (lines 253-254): update defaults mention from 30/15.0 to 10/30.0, assertions (lines 260-261): `== 30` → `== 10`, `== 15.0` → `== 30.0`; `test_uc38` docstring (lines 366-367): `start_batch_size == 30` → `start_batch_size == 10`, `start_batch_delay_sec == 15.0` → `start_batch_delay_sec == 30.0`, assertions (lines 375-376): `== 30` → `== 10`, `== 15.0` → `== 30.0` | Scenarios: Pydantic default matches defaults.py, HealthPolicyConfig without explicit adaptive_batching, and New defaults pass bounds validation. test_ut_a06 and test_ut_a07 explicitly test that the new default values (10, 30.0) pass the bounds validator. test_uc33 and test_uc38 test the default values directly. |
| tests/unit/config/test_adaptive_batching_config_to_params.py | Assertions (lines 107-108): `== 30` → `== 10`, `== 15.0` → `== 30.0` | Scenario: Pydantic default matches defaults.py. `test_to_params_with_default_values` creates `AdaptiveBatchingConfig()` with no args and asserts the default values are preserved through `to_params()`. |

## Risks & Edge Cases

- **[Risk] A test written against the old Pydantic defaults outside the known 7 files** → Mitigation: after all changes, run `poetry run pytest` to catch any missed assertions. Additional grep for `start_batch_size.*30` and `start_batch_delay_sec.*15\.0` in tests/ confirmed all sites are in the 7 files listed above (16 assertion matches + 8 helper default matches, all catalogued). Explicit argument call sites (e.g., `_make_controller(start_batch_size=30, ...)`) are intentional test inputs and do not need changing per Decision 2.
- **[Risk] `check_bounds` validator rejection** → Verified: `10 ∈ [5, 50]` and `30.0 ∈ [3.0, 120.0]`, both pass. Dedicated tests cover this explicitly: `test_ut_a06` (new `start_batch_size=10` within bounds) and `test_ut_a07` (new `start_batch_delay_sec=30.0` within bounds) in `tests/test_batching/test_adaptive_batching_config.py`.
- **[Edge Case] Controller ramp-up behavior changes due to different starting values** → `test_ic11_adaptive_batching_absent_uses_default_factory` in `tests/test_batching/test_probe_adaptive_integration.py` and `test_ut_d06_ramp_up_logic_backward_compatible` in `tests/test_batching/test_adaptive_controller.py` have ramp-up assertions that must be recalculated: batch_size 10+5=15 (was 35), batch_delay 30.0-2.0=28.0 (was 13.0). No other ramp-up tests rely on implicit defaults — they pass explicit start values.
- **[Edge Case] HealthPolicyConfig default_factory behavior is unchanged** → The `default_factory=AdaptiveBatchingConfig` callable on `HealthPolicyConfig.adaptive_batching` field is not modified. Four tests across three test files verify this behavior with the new default values: `test_ut_b04`, `test_ut_h11`, `test_uc38`, and `test_ic11`. All assert `isinstance(policy.adaptive_batching, AdaptiveBatchingConfig)` plus the value assertions being updated.
- **[Edge Case] `to_params()` preserves new defaults through the Pydantic→dataclass boundary** → `test_to_params_preserves_all_field_values` in `tests/unit/config/test_adaptive_batching_config_to_params.py` iterates all 13 fields generically (no hardcoded values) and will naturally pick up the new defaults. `test_to_params_with_default_values` has explicit assertions updated in this plan.
