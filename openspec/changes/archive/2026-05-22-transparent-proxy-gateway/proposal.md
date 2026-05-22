## Why

The Conductor (API Gateway) currently acts as a **semi-transparent proxy**: it requires explicit model/endpoint configuration in YAML, validates which models are "allowed," and selects API keys on a per-model basis. This makes the proxy a gatekeeper that decides which models and endpoints exist — a responsibility that belongs to the upstream API, not the proxy. It also forces operators to list every model and endpoint prefix (e.g., `/compatible-mode/v1/chat/completions`, `/compatible-api/v1/reranks`) in configuration, which is fragile and high-maintenance.

The goal is to transform the Conductor into a **fully transparent proxy**: a pure pipe that receives a valid key, matches it to a provider instance, injects the key where the provider expects it, and forwards everything else untouched. This lets the proxy support everything the real upstream API supports — any model, any endpoint variant, any API mode — without configuration changes.

## What Changes

- **BREAKING**: `ProviderConfig.models` field removed; replaced by `default_model: dict[str, ModelInfo]` (a dict, not a string)
- **BREAKING**: Model validation (`model_name in provider_config.models`) removed from all gateway request paths
- **BREAKING**: `GatewayCache` key pools indexed by `provider_name` only (no `provider:model` keys); `get_key_from_pool()` and `remove_key_from_pool()` signatures drop `model_name` parameter
- **BREAKING**: `default_model` config field changes type from `str` to `dict[str, ModelInfo]`
- Gateway dispatcher simplified: all instances use full-stream (no body buffering) except when debug or retry modes are active
- Gateway no longer parses request bodies for model extraction in the hot path; `parse_request_details()` becomes optional (debug/logging only)
- `shared_key_status` removed from example config files; field retained in schema for future Keeper use but gateway no longer reads it
- `get_all_valid_keys_for_caching()` uses LEFT JOIN to include keys without `key_model_status` rows (enabling transparent operation without per-model status tracking)
- Keeper health checks adapt to new `default_model` dict structure; continues to function as before using `default_model` as its model list
- `inspect()` on all providers reflects the new field name

## Capabilities

### New Capabilities

- `transparent-gateway-routing`: Gateway forwards requests to upstream without model validation or per-model key selection; URL path passed verbatim; any valid provider key works for any model request
- `provider-key-pool`: In-memory key pool indexed solely by provider instance name; round-robin rotation across all valid keys regardless of model
- `config-default-model-dict`: `default_model` is a `dict[str, ModelInfo]` used exclusively by the Keeper for health-check model resolution; gateway ignores it entirely

### Modified Capabilities

<!-- No existing specs to modify -->

## Impact

- **Config schema** (`src/config/schemas.py`): `ProviderConfig.default_model` type change, `models` field removed
- **ConfigAccessor** (`src/core/accessor.py`): `get_model_info()` and `get_default_model_info()` updated for new field structure
- **Database** (`src/db/database.py`): `get_all_valid_keys_for_caching()` query changed to LEFT JOIN; `sync()` adapts to empty `provider_models` with populated `default_model`
- **Gateway cache** (`src/services/gateway/gateway_cache.py`): ~20 lines changed — simplified pools, `shared_key_status` logic removed from gateway
- **Gateway dispatcher** (`src/services/gateway/gateway_service.py`): ~50 lines changed — simplified dispatch, model validation removed, `single_model_map` removed, Gemini special-casing merged into unified full-stream
- **Response forwarder** (`src/services/gateway/response_forwarder.py`): No code changes (model_name parameter flows through to StreamMonitor unchanged)
- **Keeper** (`src/services/keeper.py`, `src/services/key_probe.py`): ~10 lines changed — field name adaption, model resolution simplified
- **Provider implementations** (`src/providers/impl/*.py`): ~6 lines changed — field name `models` → `default_model`
- **Config examples** (`config/example_full_config.yaml`, `config/example_minimal_config.yaml`): Restructured model sections
- **Tests**: ~80+ test lines updated across ~25 test files for field renames, signature changes, and behavioral updates
