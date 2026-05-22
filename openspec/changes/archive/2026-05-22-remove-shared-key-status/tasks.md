## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b feat/remove-shared-key-status`
- [x] 1.2 Run the full test suite to establish a passing baseline: `poetry run pytest`

## 2. Config Schema — Remove shared_key_status Field

- [x] 2.1 Delete `shared_key_status: bool = False` field from `ProviderConfig` in `src/config/schemas.py` (line 534)
- [x] 2.2 Run `poetry run pyright` to verify no type errors from schema change

## 3. Database — Simplify KeyRepository Methods (src/db/database.py)

- [x] 3.1 `sync()` (lines 246-381): remove `provider_models: list[str]` parameter from signature; remove `is_shared_key` variable and `self.accessor.get_provider()` call (lines 258-260); replace if/else branching (lines 299-319) with unconditional `desired_model_state = {(key_id, ALL_MODELS_MARKER) for key_id in current_key_ids_in_db}`
- [x] 3.2 `get_keys_to_check()` (lines 382-451): remove `checked_keys_for_shared_providers` set (line 415); replace if/else branching (lines 419-450) with unconditional deduplication by `key_id` for all rows; add `ORDER BY s.model_name = '__ALL_MODELS__' DESC` to SQL query (line 410) to prefer ALL_MODELS_MARKER rows during transition
- [x] 3.3 `update_status()` (lines 453-511): remove `provider_config` reading (line 471) and `actual_model_name` variable (line 472); replace if/else branching (lines 500-511) with unconditional `params.extend([key_id, ALL_MODELS_MARKER])`
- [x] 3.4 `get_available_key()` (lines 513-562): remove `provider_config` reading (line 521) and if/else branching (lines 520-524); always set `actual_model_name = ALL_MODELS_MARKER`
- [x] 3.5 `get_status_summary()` (lines 564-590): remove `s.model_name AS model` from SELECT clause; remove `s.model_name` from GROUP BY clause
- [x] 3.6 `StatusSummaryItem` TypedDict (lines 34-38): remove `model: str` field; keep `provider: str`, `status: str`, `count: int`
- [x] 3.7 Remove obsolete comment at line 616 (`# for providers with shared_key_status=True.`)
- [x] 3.8 Remove unused `import ConfigAccessor` if no longer needed after removing `self.accessor.get_provider()` calls (check all remaining usages in KeyRepository)

## 4. Keeper — Remove models_from_config and provider_models Parameter

- [x] 4.1 In `src/services/keeper.py` (lines 150-161): remove `models_from_config = list(provider_config.default_model.keys())` computation; remove `"models_from_config": models_from_config` from `key_state` dict (line 159); simplify `ProviderKeyState` keys to only `"keys_from_files"` and `"file_map"`
- [x] 4.2 In `src/services/synchronizers/key_sync.py` (lines 195-220): remove `models_from_config = state["models_from_config"]` extraction (line 205); remove `provider_models=models_from_config` keyword argument from `self.db_manager.keys.sync()` call (line 219); update logging line (209) to remove model count reference

## 5. Metrics — Remove model Label from llm_gateway_keys_total

- [x] 5.1 In `src/metrics/backends/prometheus.py` (line 174): change `["provider", "model", "status"]` to `["provider", "status"]` in gauge label names
- [x] 5.2 In `src/metrics/backends/prometheus.py` (lines 192-200): remove `model_name = record["model"]` variable and `if model_name == "__ALL_MODELS__": model_name = "shared"` block; remove `model=model_name` keyword from `.labels()` call
- [x] 5.3 In `src/metrics/registry.py` (line 50): update `KEY_STATUS_TOTAL` description from `"by provider, model, and status"` to `"by provider and status"`

## 6. Type Check, Lint, Format

- [x] 6.1 Run `poetry run pyright` and fix all type errors
- [x] 6.2 Run `poetry run ruff check src/` and fix all lint issues
- [x] 6.3 Run `poetry run black src/` to format all source files

## 7. Testing

- [x] 7.1 Read `test-plan.md` Delegation Groups section
- [x] 7.2 Delegate group `config-schema` to @Mr.Tester (scope: `tests/unit/config/`) — 241/241 PASS
- [x] 7.3 Delegate group `db-key-repository` to @Mr.Tester (scope: `tests/unit/db/test_key_repository*.py`) — 29/29 PASS
- [x] 7.4 Delegate group `key-sync` to @Mr.Tester (scope: `tests/unit/services/synchronizers/test_key_sync.py`) — 37/37 PASS
- [x] 7.5 Delegate group `metrics` to @Mr.Tester (scope: `tests/unit/metrics/test_prometheus_backend.py`) — 8/8 PASS
- [x] 7.6 Delegate group `gateway-cache-cleanup` to @Mr.Tester (scope: `tests/unit/services/test_gateway_cache.py`, `tests/integration/test_gateway_cache_shared_key_bug.py`) — 14/14 PASS
- [x] 7.7 Review @Mr.Tester reports and fix any source-level bugs discovered — No bugs found
- [x] 7.8 Re-delegate any groups affected by source fixes — Not needed
- [x] 7.9 Verify all groups pass and coverage matches `test-plan.md`
- [x] 7.10 Run full test suite: `poetry run pytest --cov=src` — 1314 passed, 89% coverage
