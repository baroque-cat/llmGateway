## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b feat/transparent-proxy-gateway`
- [x] 1.2 Run the full test suite to establish a passing baseline: `poetry run pytest`

## 2. Config Schema — Foundation

- [x] 2.1 Change `default_model: str = ""` to `default_model: dict[str, ModelInfo] = Field(default_factory=dict)` in `src/config/schemas.py`
- [x] 2.2 Remove `models: dict[str, ModelInfo] = Field(default_factory=dict)` field from `ProviderConfig`
- [x] 2.3 Update `get_model_info()` in `src/core/accessor.py`: `provider.models.get(model_name)` → `provider.default_model.get(model_name)`
- [x] 2.4 Update `get_default_model_info()` in `src/core/accessor.py`: replace `provider.models.get(provider.default_model)` with `next(iter(provider.default_model.values()), None)`
- [x] 2.5 Run `poetry run pyright` to verify no type errors from config/accessor changes

## 3. Database — Key Visibility for Transparent Proxy

- [x] 3.1 Change `get_all_valid_keys_for_caching()` query in `src/db/database.py`: INNER JOIN → LEFT JOIN, `WHERE s.status = 'valid'` → `WHERE s.status IS NULL OR s.status = 'valid'`
- [x] 3.2 Exclude fatal statuses: add `AND (s.status IS NULL OR s.status NOT IN ('invalid_key', 'no_access', 'no_quota', 'no_model'))` to the WHERE clause
- [x] 3.3 Add `COALESCE(s.model_name, '__ALL_MODELS__')` to SELECT so keys without status rows get a model_name
- [x] 3.4 In `sync()` at line ~305: when `provider_models` is empty but `default_model` is non-empty, use `default_model.keys()` as `provider_models`

## 4. Gateway Cache — Per-Provider Pools

- [x] 4.1 In `refresh_key_pool()` line 99: change `pool_key = f"{provider_name}:{model_name}"` to `pool_key = provider_name`
- [x] 4.2 In `get_key_from_pool()`: remove `model_name` parameter; remove `shared_key_status` check (lines 157-164); always use `pool_key = provider_name`
- [x] 4.3 In `remove_key_from_pool()`: remove `model_name` parameter; remove `shared_key_status` check (lines 206-219); always use `pool_key = provider_name`
- [x] 4.4 Update all callers of `get_key_from_pool()` and `remove_key_from_pool()` to drop the `model_name` argument (handled in step 5)

## 5. Gateway Service — Transparent Dispatch

- [x] 5.1 Simplify startup pre-calculation (lines 744-840): remove `single_model_map`, remove Gemini `gemini_stream_instances` special case; `full_stream_instances` = all providers; only debug or retry providers go to buffered path
- [x] 5.2 Simplify `catch_all_endpoint` dispatch (lines 940-978): two branches — `_handle_buffered_retryable_request` if debug or retry, else `_handle_full_stream_request`
- [x] 5.3 In `_handle_full_stream_request()`: remove `model_name` parameter; call `cache.get_key_from_pool(instance_name)` without model; pass `ALL_MODELS_MARKER` to StreamMonitor; pass `ALL_MODELS_MARKER` to `_report_key_failure`
- [x] 5.4 Update log message at line 431: remove `{model_name}` from "No valid API keys for {instance}:{model}"
- [x] 5.5 In `_handle_buffered_retryable_request()`: remove model validation check (lines 537-543, "Model not permitted" error); replace `cache.get_key_from_pool(instance, details.model_name, ...)` with `cache.get_key_from_pool(instance, ...)`; replace all `remove_key_from_pool(instance, details.model_name, key_id)` with `remove_key_from_pool(instance, key_id)`
- [x] 5.6 In `_report_key_failure()`: remove `model_name` parameter; pass `ALL_MODELS_MARKER` to `db_manager.keys.update_status()`
- [x] 5.7 Remove Gemini model validation at line 960 (`if details.model_name not in provider_config.models`)

## 6. Keeper — Adapt to New Config

- [x] 6.1 In `src/services/keeper.py` line 155: change `list(provider_config.models.keys())` to `list(provider_config.default_model.keys())`
- [x] 6.2 In `src/services/key_probe.py` lines 75-85: simplify model resolution — remove `elif provider_config.models` branch; change `provider_config.default_model` check from string truthiness to dict truthiness; use `next(iter(provider_config.default_model.keys()))`

## 7. Provider Implementations — Field Rename

- [x] 7.1 `src/providers/impl/openai_like.py` line 176: `self.config.models.get(model)` → `self.config.default_model.get(model)`
- [x] 7.2 `src/providers/impl/openai_like.py` line 259: `list(self.config.models.keys())` → `list(self.config.default_model.keys())`
- [x] 7.3 `src/providers/impl/anthropic.py` line 215: `self.config.models.get(model)` → `self.config.default_model.get(model)`
- [x] 7.4 `src/providers/impl/anthropic.py` line 293: `list(self.config.models.keys())` → `list(self.config.default_model.keys())`
- [x] 7.5 `src/providers/impl/gemini.py` line 29: `self.config.models.get(model)` → `self.config.default_model.get(model)`
- [x] 7.6 `src/providers/impl/gemini_base.py` line 102: `list(self.config.models.keys())` → `list(self.config.default_model.keys())`

## 8. Config Examples — YAML Restructure

- [x] 8.1 `config/example_full_config.yaml`: remove all `shared_key_status: false` lines; rename `models:` → `default_model:` for all three providers; remove `default_model: "..."` string lines
- [x] 8.2 `config/example_minimal_config.yaml`: same changes

## 9. Type Check, Lint, Format

- [x] 9.1 Run `poetry run pyright` and fix all type errors
- [x] 9.2 Run `poetry run ruff check src/` and fix all lint issues
- [x] 9.3 Run `poetry run black src/` to format all source files

## 10. Testing

- [x] 10.1 Read `test-plan.md` Delegation Groups section
- [x] 10.2 Delegate group `config-schema` to @Mr.Tester (scope: `tests/unit/config/`, `tests/unit/core/test_accessor_providers.py`)
- [x] 10.3 Delegate group `gateway-cache` to @Mr.Tester (scope: `tests/unit/services/test_gateway_cache.py`)
- [x] 10.4 Delegate group `gateway-service` to @Mr.Tester (scope: `tests/unit/services/test_gateway_transparent_routing.py`, `tests/unit/services/test_gateway_core.py`)
- [x] 10.5 Delegate group `database-keys` to @Mr.Tester (scope: `tests/unit/db/test_key_repository_get_available_key.py`)
- [x] 10.6 Delegate group `keeper-probe` to @Mr.Tester (scope: `tests/unit/services/test_keeper.py`, `tests/unit/core/test_probes_dispatcher.py`)
- [x] 10.7 Delegate group `providers` to @Mr.Tester (scope: `tests/unit/providers/`, `tests/unit/providers/impl/`)
- [x] 10.8 Delegate group `config-examples` to @Mr.Tester (scope: `tests/integration/test_config_examples.py`)
- [x] 10.9 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 10.10 Re-delegate any groups affected by source fixes
- [x] 10.11 Verify all groups pass and coverage matches `test-plan.md`
- [x] 10.12 Run full test suite: `poetry run pytest --cov=src`
