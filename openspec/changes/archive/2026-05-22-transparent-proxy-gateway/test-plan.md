# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| config-default-model-dict | default_model is a dict of ModelInfo | Single model in default_model | tests/unit/config/test_default_model_dict.py | test_single_model_in_default_model | config-schema |
| config-default-model-dict | default_model is a dict of ModelInfo | Empty default_model is valid | tests/unit/config/test_default_model_dict.py | test_empty_default_model_is_valid | config-schema |
| config-default-model-dict | models field is removed from ProviderConfig | Config validation rejects models field | tests/unit/config/test_default_model_dict.py | test_config_validation_rejects_models_field | config-schema |
| config-default-model-dict | ConfigAccessor get_model_info uses default_model | Model info retrieved from default_model | tests/unit/core/test_accessor_providers.py | test_get_model_info_from_default_model | config-schema |
| config-default-model-dict | ConfigAccessor get_default_model_info returns first ModelInfo | Default model info returned | tests/unit/core/test_accessor_providers.py | test_get_default_model_info_returns_first_value | config-schema |
| config-default-model-dict | ConfigAccessor get_default_model_info returns first ModelInfo | Empty default_model returns None | tests/unit/core/test_accessor_providers.py | test_get_default_model_info_returns_none_for_empty | config-schema |
| config-default-model-dict | Keeper uses default_model as its model list | Models extracted from default_model for sync | tests/unit/services/test_keeper.py | test_models_extracted_from_default_model_for_sync | keeper-probe |
| config-default-model-dict | KeyProbe resolves model from default_model dict | Shared-key check resolved from default_model | tests/unit/core/test_probes_dispatcher.py | test_shared_key_check_resolved_from_default_model | keeper-probe |
| config-default-model-dict | KeyProbe resolves model from default_model dict | Empty default_model on shared-key check returns BAD_REQUEST | tests/unit/core/test_probes_dispatcher.py | test_empty_default_model_shared_key_returns_bad_request | keeper-probe |
| config-default-model-dict | Provider implementations access default_model instead of models | Health check URL uses default_model | tests/unit/providers/impl/test_openai_like.py | test_health_check_url_uses_default_model | providers |
| config-default-model-dict | Provider implementations access default_model instead of models | inspect() returns keys from default_model | tests/unit/providers/test_base.py | test_inspect_returns_keys_from_default_model | providers |
| provider-key-pool | Key pools are indexed by provider name only | Pool key is provider name | tests/unit/services/test_gateway_cache.py | test_pool_key_is_provider_name_only | gateway-cache |
| provider-key-pool | Key pools are indexed by provider name only | Multiple models share one pool | tests/unit/services/test_gateway_cache.py | test_multiple_models_share_one_pool | gateway-cache |
| provider-key-pool | get_key_from_pool accepts provider_name only | Key retrieved without model name | tests/unit/services/test_gateway_cache.py | test_get_key_from_pool_without_model_name | gateway-cache |
| provider-key-pool | get_key_from_pool accepts provider_name only | No valid keys available | tests/unit/services/test_gateway_cache.py | test_get_key_from_pool_returns_none_when_empty | gateway-cache |
| provider-key-pool | remove_key_from_pool accepts provider_name and key_id only | Key removed from provider pool | tests/unit/services/test_gateway_cache.py | test_remove_key_from_pool_by_provider_and_key_id | gateway-cache |
| provider-key-pool | Gateway cache ignores shared_key_status config | shared_key_status has no effect on pool selection | tests/unit/services/test_gateway_cache.py | test_shared_key_status_has_no_effect_on_pool | gateway-cache |
| provider-key-pool | Keys without key_model_status rows are included in cache | Key without status row is cached | tests/unit/db/test_key_repository_get_available_key.py | test_key_without_status_row_is_cached | database-keys |
| provider-key-pool | Keys without key_model_status rows are included in cache | Key with fatal status is excluded | tests/unit/db/test_key_repository_get_available_key.py | test_key_with_fatal_status_is_excluded | database-keys |
| transparent-gateway-routing | Gateway forwards requests without model validation | Unknown model forwarded transparently | tests/unit/services/test_gateway_transparent_routing.py | test_unknown_model_forwarded_transparently | gateway-service |
| transparent-gateway-routing | Gateway forwards requests without model validation | Model validation code removed | tests/unit/services/test_gateway_transparent_routing.py | test_no_model_membership_check_in_hot_path | gateway-service |
| transparent-gateway-routing | Gateway passes URL path verbatim to upstream | Compatible-mode path forwarded unchanged | tests/unit/services/test_gateway_transparent_routing.py | test_compatible_mode_path_forwarded_unchanged | gateway-service |
| transparent-gateway-routing | Gateway passes URL path verbatim to upstream | Compatible-api path forwarded unchanged | tests/unit/services/test_gateway_transparent_routing.py | test_compatible_api_path_forwarded_unchanged | gateway-service |
| transparent-gateway-routing | Full-stream mode is the default for all instances | Standard instance uses full stream | tests/unit/services/test_gateway_transparent_routing.py | test_standard_instance_uses_full_stream | gateway-service |
| transparent-gateway-routing | Full-stream mode is the default for all instances | Debug mode forces buffered handling | tests/unit/services/test_gateway_transparent_routing.py | test_debug_mode_forces_buffered_handling | gateway-service |
| transparent-gateway-routing | Full-stream mode is the default for all instances | Retry mode forces buffered handling | tests/unit/services/test_gateway_transparent_routing.py | test_retry_mode_forces_buffered_handling | gateway-service |
| transparent-gateway-routing | Gateway does not parse request bodies in full-stream path | Full-stream bypasses body parsing | tests/unit/services/test_gateway_transparent_routing.py | test_full_stream_bypasses_body_parsing | gateway-service |
| transparent-gateway-routing | Gemini URL-based model parsing is preserved for logging | Gemini full-stream extracts model from URL for logs | tests/unit/providers/impl/test_gemini.py | test_gemini_full_stream_extracts_model_from_url_for_logs | providers |

## Delegation Groups

### Group: config-schema
**Scope:** `tests/unit/config/`, `tests/unit/core/test_accessor_providers.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/config/test_default_model_dict.py | 3 | NEW |
| tests/unit/core/test_accessor_providers.py | 3 | MODIFY |

### Group: gateway-cache
**Scope:** `tests/unit/services/test_gateway_cache.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/services/test_gateway_cache.py | 6 | MODIFY |

### Group: gateway-service
**Scope:** `tests/unit/services/test_gateway_transparent_routing.py`, `tests/unit/services/test_gateway_core.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/services/test_gateway_transparent_routing.py | 8 | NEW |
| tests/unit/services/test_gateway_core.py | 0 | MODIFY |

### Group: database-keys
**Scope:** `tests/unit/db/test_key_repository_get_available_key.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/db/test_key_repository_get_available_key.py | 2 | MODIFY |

### Group: keeper-probe
**Scope:** `tests/unit/services/test_keeper.py`, `tests/unit/core/test_probes_dispatcher.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/services/test_keeper.py | 1 | MODIFY |
| tests/unit/core/test_probes_dispatcher.py | 2 | MODIFY |

### Group: providers
**Scope:** `tests/unit/providers/`, `tests/unit/providers/impl/`

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/providers/test_base.py | 1 | MODIFY |
| tests/unit/providers/impl/test_openai_like.py | 1 | MODIFY |
| tests/unit/providers/impl/test_gemini.py | 1 | MODIFY |
| tests/unit/providers/impl/test_anthropic_integration.py | 0 | MODIFY |
| tests/unit/providers/impl/test_anthropic_core.py | 0 | MODIFY |
| tests/unit/providers/impl/conftest.py | 0 | MODIFY |
| tests/unit/providers/test_error_parsing_scenarios.py | 0 | MODIFY |
| tests/unit/providers/test_error_parsing_edge_cases.py | 0 | MODIFY |

### Group: config-examples
**Scope:** `tests/integration/test_config_examples.py`

| Test File | Scenarios | Action |
|---|---|---|
| tests/integration/test_config_examples.py | 0 | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| tests/unit/core/test_accessor_providers.py | Replace `default_model="model1"` (str) with `default_model={"model1": ModelInfo()}` (dict); add tests for `get_model_info()` and `get_default_model_info()` | `default_model` field changed from `str` to `dict[str, ModelInfo]`; new accessor methods added |
| tests/unit/services/test_gateway_core.py | Replace `mock_provider_config.models = {"gpt-4": MagicMock()}` with `mock_provider_config.default_model = {"gpt-4": ModelInfo()}` | `models` field removed; `default_model` dict replaces it |
| tests/integration/test_gateway_refactor.py | Replace all 21 occurrences of `provider_config.models = {"gpt-4": {}}` with `provider_config.default_model = {"gpt-4": ModelInfo()}` | `models` field removed from `ProviderConfig` |
| tests/integration/test_gateway_cache_shared_key_bug.py | Replace `ALL_MODELS_MARKER` model_name usage in pool keys with provider-name-only keys; replace `provider_config.models` with `provider_config.default_model` | Pool keys no longer include model suffix; `models` field removed |
| tests/integration/test_gateway_retry_synergy.py | Replace `models` field references with `default_model` dict | `models` field removed from `ProviderConfig` |
| tests/security/test_gateway_auth.py | Replace `provider_config.models = {"gpt-4": ModelInfo()}` with `provider_config.default_model = {"gpt-4": ModelInfo()}` | `models` field removed from `ProviderConfig` |
| tests/integration/test_gateway_dispatcher_routing.py | Replace `{"models": {"gpt-4": ModelInfo()}}` kwargs with `{"default_model": {"gpt-4": ModelInfo()}}` | `models` field removed; routing no longer validates model membership |
| tests/integration/test_gateway_full_duplex_streaming.py | Replace `models={"gpt-4": ModelInfo()}` and multi-model dicts with `default_model=` equivalents | `models` field removed; full-stream is now default |
| tests/integration/test_stream_closed_bug.py | Replace `config.models = {"gpt-4": ModelInfo()}` with `config.default_model = {"gpt-4": ModelInfo()}` | `models` field removed from `ProviderConfig` |
| tests/integration/test_unified_error_parsing.py | Replace `config.models = {"gpt-4": ...}` with `config.default_model = {"gpt-4": ...}` | `models` field removed from `ProviderConfig` |
| tests/unit/providers/test_error_parsing_scenarios.py | Replace `mock_config.default_model = "gpt-4"` (str) and `mock_config.models = {}` with `mock_config.default_model = {"gpt-4": ModelInfo()}` (dict) | `default_model` changed from str to dict; `models` removed |
| tests/unit/providers/test_error_parsing_edge_cases.py | Replace `mock_config.default_model = "gpt-4"` (str) and `mock_config.models = {}` with `mock_config.default_model = {"gpt-4": ModelInfo()}` (dict) | `default_model` changed from str to dict; `models` removed |
| tests/unit/providers/impl/test_gemini.py | Replace `mock_config.default_model = "gemini-pro"` (str) + `mock_config.models = {}` with `mock_config.default_model = {"gemini-pro": ModelInfo()}` (dict); replace `provider.config.models = {...}` with `provider.config.default_model = {...}` | `default_model` changed from str to dict; `models` removed |
| tests/unit/providers/impl/test_openai_like.py | Replace `mock_config.default_model = "gpt-4"` (str) + `mock_config.models = {}` with `mock_config.default_model = {"gpt-4": ModelInfo()}` (dict); replace `provider.config.models = {...}` with `provider.config.default_model = {...}` | `default_model` changed from str to dict; `models` removed |
| tests/unit/providers/impl/test_anthropic_integration.py | Replace `models={"claude-3-opus": ModelInfo()}` constructor kwarg with `default_model={"claude-3-opus": ModelInfo()}`; update assertions from `provider_config.models` to `provider_config.default_model`; update YAML fixture strings | `models` field removed; `default_model` dict replaces it |
| tests/unit/providers/impl/conftest.py | Replace `mock_config.default_model = "claude-3-opus-..."` (str) + `mock_config.models = models` with `mock_config.default_model = {"claude-3-opus-...": ModelInfo()}` (dict); remove `models` parameter from factory function or rename to `default_model` | Fixture factory must produce `default_model` dict instead of str + separate `models` dict |
| tests/integration/conftest.py | Replace `config.models = models` with `config.default_model = default_model`; rename `models` parameter to `default_model`; change default from `{"gpt-4": ModelInfo()}` dict assignment | Integration fixture factory must produce `default_model` dict |
| tests/e2e/test_gateway_request_logging.py | Replace `config.models = models` with `config.default_model = default_model`; rename `models` kwarg to `default_model` | Fixture factory must produce `default_model` dict |
| tests/unit/services/test_gateway_cache.py | Update all pool-key construction to use provider-name-only keys (remove `:{model_name}` and `:{ALL_MODELS_MARKER}` suffixes); update `get_key_from_pool()` and `remove_key_from_pool()` call signatures to drop `model_name` arg; add 6 new test scenarios for provider-only pool behavior | Pool keys simplified; method signatures changed; shared_key_status no longer read |
| tests/unit/services/test_gateway_service_stream_monitor.py | Update `model_name` parameter usage — in transparent mode the model may be unknown or `ALL_MODELS_MARKER`; ensure `_format_model_name()` handles empty/unknown model names for logging | StreamMonitor must handle transparent-mode model naming where model may not be resolved |
| tests/integration/test_penalty_behavior.py | Replace `provider_config.models = {"gpt-4": MagicMock()}` with `provider_config.default_model = {"gpt-4": ModelInfo()}` | `models` field removed from `ProviderConfig` |
| tests/integration/test_config_examples.py | Replace assertions on `provider.models` (e.g., `gemini.models["gemini-2.5-flash"]`) with `provider.default_model["gemini-2.5-flash"]`; update all `models` dict access to `default_model` dict access | `models` field removed; example YAML configs must use `default_model` key |

## Risks & Edge Cases

- **[Keys without status rows treated as valid]** Keys that have no `key_model_status` row (e.g., provider with empty `default_model`) are treated as valid by default → `tests/unit/db/test_key_repository_get_available_key.py::test_key_without_status_row_is_cached` — verify LEFT JOIN returns such keys with `model_name = '__ALL_MODELS__'` and that they are placed in the provider pool
- **[Bad keys used before Keeper detects them]** A newly added key with no status row could be routed to a client before the Keeper health-check cycle marks it invalid → `tests/unit/services/test_gateway_cache.py::test_key_without_status_row_available_in_pool` — verify that a key with no status row is immediately available after `refresh_key_pool()` and that subsequent Keeper detection of fatal status triggers `remove_key_from_pool()`
- **[Model name unavailable for gateway logging]** In full-stream mode, the gateway does not parse request bodies, so the model name may be `<all models>` or empty in `GATEWAY_ACCESS` log lines → `tests/unit/services/test_gateway_service_stream_monitor.py::test_format_model_name_all_models_marker` — verify `_format_model_name()` produces a readable log entry when model is `ALL_MODELS_MARKER` or empty string
- **[Retry iterates over all provider keys]** Retry mode rotates through all keys in the provider pool rather than a per-model subset, potentially exhausting keys faster → `tests/integration/test_gateway_retry_synergy.py` — verify retry rotation uses provider-level pool and does not skip keys that were previously assigned to different models
- **[Breaking config change for operators]** YAML `models:` section must be renamed to `default_model:` and `default_model: "string"` must be removed → `tests/integration/test_config_examples.py` — verify example config files parse correctly with new schema and that old `models:` key is rejected with `extra_forbid` error
- **[Empty default_model with shared-key provider]** A provider with `default_model: {}` and shared keys has no model to resolve for `ALL_MODELS_MARKER` health checks → `tests/unit/core/test_probes_dispatcher.py::test_empty_default_model_shared_key_returns_bad_request` — verify `_check_resource()` returns `CheckResult.fail(ErrorReason.BAD_REQUEST)` when `default_model` is empty and `model_name = "__ALL_MODELS__"`
- **[Gemini URL parsing in full-stream is non-essential but retained]** The Gemini `parse_request_details()` path parser extracts model from URL but this info is not used for routing → `tests/unit/providers/impl/test_gemini.py::test_gemini_full_stream_extracts_model_from_url_for_logs` — verify model extraction works with empty body `b""` and that the result does not influence key selection or URL construction
- **[URL path verbatim forwarding with special characters]** Paths containing query strings, encoded characters, or multiple segments must be forwarded unchanged → `tests/unit/services/test_gateway_transparent_routing.py::test_compatible_api_path_forwarded_unchanged` — verify the upstream URL is exactly `api_base_url + request.path + request.query_string` with no transformation