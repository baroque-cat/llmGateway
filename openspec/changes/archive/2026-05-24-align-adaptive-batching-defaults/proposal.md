## Why

`AdaptiveBatchingConfig` has divergent defaults between the two sources of truth: `schemas.py` Pydantic `Field(default=…)` (Tier 3) specifies `start_batch_size=30, start_batch_delay_sec=15.0`, while `defaults.py` (Tier 1) and `example_full_config.yaml` both specify `start_batch_size=10, start_batch_delay_sec=30.0`. This means users who omit the `adaptive_batching` section silently get different runtime behavior (30/15.0 from Pydantic) than users who include it but omit start values (10/30.0 from deepmerge). The three-tier default system must produce identical results regardless of which layer supplies the value.

## What Changes

- Change Pydantic `Field(default=…)` in `AdaptiveBatchingConfig` (schemas.py lines 132-133) from `30`/`15.0` to `10`/`30.0` — matching `defaults.py` and the example config
- Update 4 test files that assert the old Pydantic defaults (30/15.0) to expect the new values (10/30.0)
- No changes to `defaults.py`, `example_full_config.yaml`, or the loader

## Capabilities

### New Capabilities

- `config-consistency`: Config default values are consistent across all three tiers of the default system (hardcoded `defaults.py` dict, user YAML deepmerge, Pydantic `Field(default=…)`)

### Modified Capabilities

<!-- None. This is a values-only fix, no requirement changes. -->

## Impact

- **Affected source**: `src/config/schemas.py` (2 lines — Pydantic Field defaults)
- **Affected tests**: `tests/unit/config/test_validator.py`, `tests/unit/core/test_probes_dispatcher.py`, `tests/test_batching/test_probe_adaptive_integration.py`, `tests/test_batching/test_adaptive_security.py` (assertion values + test helper signatures)
- **No API changes, no breaking changes, no schema changes**
