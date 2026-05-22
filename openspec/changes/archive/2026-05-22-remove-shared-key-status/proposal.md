## Why

The `shared_key_status` field was originally designed to optimize providers where all API keys share a single rate-limit or quota (e.g., account-level limits). The transparent proxy gateway change (`2026-05-22-transparent-proxy-gateway`) removed all gateway-side usage of this field but kept it in the schema and Keeper-side database branching "for future use." That future never came — the architecture has moved decisively toward every provider behaving uniformly as a transparent pipe. The field now creates dead branching in four database methods (sync, get_keys_to_check, update_status, get_available_key) where both branches produce identical results, and causes the Prometheus `llm_gateway_keys_total` metric to carry a vestigial `model="shared"` label that provides zero information.

## What Changes

- **BREAKING**: `ProviderConfig.shared_key_status` field removed from config schema — configs with this field will fail validation
- **BREAKING**: `KeyRepository.sync()` `provider_models` parameter removed — all call-sites updated
- **BREAKING**: `StatusSummaryItem.model` field removed — Prometheus `llm_gateway_keys_total` drops the `model` label, showing only `provider` and `status`
- `KeyRepository.sync()` always creates `__ALL_MODELS__` key-model associations (one per key, no per-model rows)
- `KeyRepository.get_keys_to_check()` always deduplicates by `key_id` (one check per key, not per key-model pair)
- `KeyRepository.update_status()` always uses `__ALL_MODELS__` in the WHERE clause
- `KeyRepository.get_available_key()` always substitutes `__ALL_MODELS__` as model name
- `KeyRepository.get_status_summary()` SQL no longer groups by `model_name`
- Prometheus metrics collector no longer transforms `__ALL_MODELS__` → `"shared"` label
- Keeper continues health-checking using `default_model` dict for `__ALL_MODELS__` model resolution (unchanged behavior)
- All test files updated to remove `shared_key_status` from mock configs

## Capabilities

### New Capabilities

- `remove-shared-key-status`: Remove `shared_key_status` field from config schema and eliminate all conditional branching in `KeyRepository` methods (sync, get_keys_to_check, update_status, get_available_key). All providers uniformly use `__ALL_MODELS__` for key-model associations.
- `metrics-no-model-label`: Remove the `model` dimension from the `llm_gateway_keys_total` Prometheus metric. The metric shows only `provider` and `status` labels, reflecting the architecture where there is no per-model distinction — every provider instance has a single key status per key.

### Modified Capabilities

- `provider-key-pool`: Remove requirement "Gateway cache ignores shared_key_status config" — the field no longer exists, so this requirement is obsolete. Remove the associated scenario.

## Impact

- **Config schema** (`src/config/schemas.py`): 1 line deleted — `shared_key_status: bool = False`
- **Database** (`src/db/database.py`): ~70 lines simplified — 4 methods lose conditional branching, 1 TypedDict loses field, 1 SQL loses GROUP BY clause, 1 comment removed
- **Metrics** (`src/metrics/backends/prometheus.py`, `src/metrics/registry.py`): ~10 lines — Gauge definition drops `model` label, description updated
- **Keeper** (`src/services/keeper.py`): ~5 lines — `models_from_config` computation removed, no longer passed to sync
- **Key syncer** (`src/services/synchronizers/key_sync.py`): ~3 lines — `provider_models` parameter removed from sync call
- **Key probe** (`src/services/key_probe.py`): unchanged — already resolves `__ALL_MODELS__` independently
- **Gateway**: unchanged — already ignores `shared_key_status` since transparent-proxy-gateway change
- **Config examples**: already clean (no `shared_key_status` lines) since transparent-proxy-gateway change
- **Database schema**: no migration needed — `key_model_status` `model_name TEXT NOT NULL` column and `ALL_MODELS_MARKER` sentinel remain as internal implementation details
- **Tests**: ~60 lines across ~12 files — mock configs updated, parameterized tests simplified
