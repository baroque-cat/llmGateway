# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| remove-shared-key-status | ProviderConfig excludes shared_key_status field | shared_key_status field is absent from schema | `tests/unit/config/test_shared_key_status_removal.py` | `test_shared_key_status_field_absent_from_schema` | config-schema |
| remove-shared-key-status | ProviderConfig excludes shared_key_status field | Default config is valid without shared_key_status | `tests/unit/config/test_shared_key_status_removal.py` | `test_default_config_valid_without_shared_key_status` | config-schema |
| remove-shared-key-status | sync() unconditionally uses ALL_MODELS_MARKER | sync creates ALL_MODELS_MARKER associations for any provider | `tests/unit/db/test_key_repository_sync.py` | `test_sync_all_providers_use_all_models_marker` | db-key-repository |
| remove-shared-key-status | sync() unconditionally uses ALL_MODELS_MARKER | sync removes legacy per-model rows | `tests/unit/db/test_key_repository_sync.py` | `test_sync_removes_legacy_per_model_rows` | db-key-repository |
| remove-shared-key-status | sync() does not accept provider_models parameter | sync() signature excludes provider_models | `tests/unit/db/test_key_repository_sync.py` | `test_sync_signature_no_provider_models_param` | db-key-repository |
| remove-shared-key-status | sync() does not accept provider_models parameter | Call-sites do not pass provider_models | `tests/unit/services/synchronizers/test_key_sync.py` | `test_sync_calls_do_not_pass_provider_models` | key-sync |
| remove-shared-key-status | get_keys_to_check() deduplicates for all providers | Multiple model rows deduplicated to one per key | `tests/unit/db/test_key_repository.py` | `test_get_keys_to_check_deduplicates_all_providers` | db-key-repository |
| remove-shared-key-status | get_keys_to_check() deduplicates for all providers | ALL_MODELS_MARKER rows preferred during deduplication | `tests/unit/db/test_key_repository.py` | `test_get_keys_to_check_prefers_all_models_marker` | db-key-repository |
| remove-shared-key-status | update_status() always queries by ALL_MODELS_MARKER | Status update uses ALL_MODELS_MARKER in WHERE clause | `tests/unit/db/test_key_repository_update_status.py` | `test_update_status_always_uses_all_models_marker` | db-key-repository |
| remove-shared-key-status | get_available_key() always substitutes ALL_MODELS_MARKER | Model name always substituted to ALL_MODELS_MARKER | `tests/unit/db/test_key_repository_get_available_key.py` | `test_get_available_key_always_substitutes_all_models` | db-key-repository |
| metrics-no-model-label | llm_gateway_keys_total has no model label | Gauge registered without model label | `tests/unit/metrics/test_prometheus_backend.py` | `test_gauge_registered_without_model_label` | metrics |
| metrics-no-model-label | llm_gateway_keys_total has no model label | Metric value set with provider and status only | `tests/unit/metrics/test_prometheus_backend.py` | `test_collect_from_db_updates_gauge_values` | metrics |
| metrics-no-model-label | __ALL_MODELS__ is not transformed in metrics | No model transformation code | `tests/unit/metrics/test_prometheus_backend.py` | `test_no_model_transformation_code` | metrics |
| metrics-no-model-label | StatusSummaryItem has no model field | TypedDict definition excludes model | `tests/unit/db/test_key_repository_status_summary.py` | `test_status_summary_item_no_model_field` | db-key-repository |
| metrics-no-model-label | get_status_summary() does not group by model | SQL query excludes model dimension | `tests/unit/db/test_key_repository_status_summary.py` | `test_get_status_summary_no_model_group_by` | db-key-repository |

## Delegation Groups

### Group: config-schema
**Scope:** `tests/unit/config/`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_shared_key_status_removal.py` | 2 | NEW |

### Group: db-key-repository
**Scope:** `tests/unit/db/test_key_repository.py`, `tests/unit/db/test_key_repository_sync.py`, `tests/unit/db/test_key_repository_update_status.py`, `tests/unit/db/test_key_repository_get_available_key.py`, `tests/unit/db/test_key_repository_status_summary.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/db/test_key_repository_sync.py` | 3 | MODIFY |
| `tests/unit/db/test_key_repository.py` | 2 | MODIFY |
| `tests/unit/db/test_key_repository_update_status.py` | 1 | MODIFY |
| `tests/unit/db/test_key_repository_get_available_key.py` | 1 | MODIFY |
| `tests/unit/db/test_key_repository_status_summary.py` | 2 | MODIFY |

### Group: key-sync
**Scope:** `tests/unit/services/synchronizers/test_key_sync.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/synchronizers/test_key_sync.py` | 1 | MODIFY |

### Group: metrics
**Scope:** `tests/unit/metrics/test_prometheus_backend.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/metrics/test_prometheus_backend.py` | 3 | MODIFY |

### Group: gateway-cache-cleanup
**Scope:** `tests/unit/services/test_gateway_cache.py`, `tests/integration/test_gateway_cache_shared_key_bug.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_cache.py` | 0 (modify only) | MODIFY |
| `tests/integration/test_gateway_cache_shared_key_bug.py` | 0 (modify only) | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/unit/config/test_shared_key_status_removal.py` | NEW FILE: add `test_shared_key_status_field_absent_from_schema`, `test_yaml_with_shared_key_status_true_rejected`, `test_yaml_with_shared_key_status_false_rejected`, `test_default_config_valid_without_shared_key_status` | Spec: "ProviderConfig SHALL NOT contain a shared_key_status field" and "YAML files containing shared_key_status SHALL fail validation" |
| `tests/unit/db/test_key_repository_sync.py` | Remove `provider_config_shared` parameter. Remove `test_sync_with_shared_key_status` and `test_sync_with_empty_models`. Drop `provider_models` from all `repo.sync()` calls. Add new tests for unified ALL_MODELS_MARKER behavior and signature change. | Spec: "sync() unconditionally uses ALL_MODELS_MARKER" + "sync() does not accept provider_models". Design D2. |
| `tests/unit/db/test_key_repository.py` | Remove `shared_key_status=False` from mock configs. Remove `test_get_keys_to_check_mixed_providers`. Rename/rewrite shared-key tests for universal deduplication. Add ALL_MODELS_MARKER preference test. | Spec: "get_keys_to_check() deduplicates for all providers". Design risk: transition-period row mix. |
| `tests/unit/db/test_key_repository_update_status.py` | Remove `provider_config_shared` parameter. Remove non-shared path test. Rename shared test to reflect universal behavior. | Spec: "update_status() always queries by ALL_MODELS_MARKER". |
| `tests/unit/db/test_key_repository_get_available_key.py` | Remove `provider_config_shared` parameter. Replace old shared-key test with universal substitution test. | Spec: "get_available_key() always substitutes ALL_MODELS_MARKER". Design D5. |
| `tests/unit/db/test_key_repository_status_summary.py` | Remove `model` field assertions. Remove shared-key-specific tests. Add TypedDict and SQL clause inspection tests. | Spec: "StatusSummaryItem has no model field" + "get_status_summary() does not group by model". |
| `tests/unit/services/synchronizers/test_key_sync.py` | Remove `provider_models` from state dicts and assertions. Remove `shared_key_status=False` from mock config. | Spec: "Call-sites do not pass provider_models". Design D2. |
| `tests/unit/metrics/test_prometheus_backend.py` | Rewrite metric tests: remove `model` label from gauge assertions. Add no-transformation test. | Spec: "llm_gateway_keys_total has no model label" + "no __ALL_MODELS__ transformation". Design D3. |
| `tests/unit/services/test_gateway_cache.py` | Remove all `shared_key_status` assignments from mock configs. Remove two shared-key-specific test functions. | Design D1: field removed from schema. |
| `tests/integration/test_gateway_cache_shared_key_bug.py` | Remove `shared_key_status=True` assignment. Remove unused `ProviderConfig` import. | Design D1: field removed from schema. |

## Risks & Edge Cases

- **[YAML configs with shared_key_status fail validation]** → test `test_yaml_with_shared_key_status_true_rejected` and `test_yaml_with_shared_key_status_false_rejected` in `tests/unit/config/test_shared_key_status_removal.py`
- **[First sync() deletes old per-model rows]** → test `test_sync_removes_legacy_per_model_rows` in `tests/unit/db/test_key_repository_sync.py`
- **[Transition-period row mix in get_keys_to_check()]** → test `test_get_keys_to_check_prefers_all_models_marker` in `tests/unit/db/test_key_repository.py`
- **[Empty ProviderConfig still validates]** → test `test_default_config_valid_without_shared_key_status` in `tests/unit/config/test_shared_key_status_removal.py`
- **[sync() with 0, 1, 3+ keys]** → parameterized within `test_sync_all_providers_use_all_models_marker` in `tests/unit/db/test_key_repository_sync.py`
- **[get_status_summary() with empty DB]** → `test_get_status_summary_no_model_group_by` in `tests/unit/db/test_key_repository_status_summary.py`
- **[Metrics gauge re-registration after label change]** → use unique gauge name or private registry in `tests/unit/metrics/test_prometheus_backend.py`
- **[No shared_key_status in ProviderConfig.model_fields]** → `test_shared_key_status_field_absent_from_schema` in `tests/unit/config/test_shared_key_status_removal.py`
- **[Call-sites never construct provider_models lists]** → `test_sync_calls_do_not_pass_provider_models` in `tests/unit/services/synchronizers/test_key_sync.py`
