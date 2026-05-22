## Context

The llmGateway Conductor (API Gateway) currently acts as a semi-transparent proxy. It requires explicit model definitions in YAML configuration (`endpoint_suffix`, `test_payload` per model), validates incoming model names against that list, and selects API keys on a per-model basis from `key_model_status` rows. This creates tight coupling between what the upstream API supports and what the proxy configuration declares, forcing operators to maintain model lists that duplicate the upstream API's capabilities.

The Keeper (background health-check worker) relies on the same `models` dict plus a `default_model: str` field to determine which models to health-check. Both components share `ProviderConfig` as their configuration source.

After this change, the Conductor becomes a pure transparent pipe: it no longer inspects model names for routing decisions, validates models, or selects keys per-model. The Keeper continues to perform health checks using the restructured `default_model` dict.

## Goals / Non-Goals

**Goals:**
- Conductor forwards requests without model validation or per-model key selection
- Gateway cache key pools indexed by provider instance name only
- All valid keys for a provider are eligible for any incoming request to that provider
- Full-stream mode becomes the default (no body buffering in the hot path)
- Keeper continues to health-check using `default_model` dict
- Config schema simplified: one `default_model` dict replaces both `default_model: str` and `models: dict`
- `shared_key_status` removed from gateway logic (retained in schema for future Keeper use)
- Gateway logs remain informative; metrics unaffected (gateway doesn't emit request metrics directly)

**Non-Goals:**
- The proxy does NOT discover available models from upstream APIs
- The proxy does NOT implement per-model access control (delegated to upstream API or external systems)
- Keeper behavior unchanged aside from field name adaptation
- No changes to health-check probing, purge, vacuum, or key export mechanisms
- No changes to the `key_model_status` database schema or its role in the Keeper
- No dynamic provider registration or runtime config reload

## Decisions

### D1: `default_model` becomes `dict[str, ModelInfo]`, `models` removed

**Rationale:** The Keeper needs to know which model(s) to health-check, and needs `endpoint_suffix` and `test_payload` for each. Placing this under a single `default_model` dict (with model names as keys) keeps the Keeper's configuration self-contained. The gateway ignores this section entirely.

**Alternatives considered:**
- Keep `models` dict and rename `default_model: str` → `check_model: dict` — creates two dict fields with overlapping semantics.
- Make `default_model` accept `str | dict[str, ModelInfo]` — adds validation complexity with discriminated union.
- Keep `models` and drop `default_model` entirely — loses the semantic distinction between "models the Keeper checks" and "models the gateway exposes" (which no longer exists after this change).

### D2: Gateway cache pools keyed by `provider_name` only

**Rationale:** The `shared_key_status: true` code path already demonstrates that per-provider key pools work correctly. This change universalizes that behavior, removing the `shared_key_status` check from the gateway entirely. The pool key changes from `"provider:model"` to just `"provider"`, and `get_key_from_pool()` / `remove_key_from_pool()` drop their `model_name` parameter.

**Alternatives considered:**
- Keep per-model pools but relax model validation — defeats the purpose; key selection still constrained.
- Use `ALL_MODELS_MARKER` as pool key prefix — adds unnecessary indirection; direct provider name is simpler.

### D3: LEFT JOIN for `get_all_valid_keys_for_caching()`

**Rationale:** When `default_model` is empty (no models configured at all), `sync()` creates no `key_model_status` rows. The gateway must still be able to use those keys. Using LEFT JOIN with `WHERE s.status IS NULL OR s.status = 'valid'` treats keys without status rows as valid by default. Fatal statuses (`invalid_key`, `no_access`, `no_quota`) are still excluded.

**Alternatives considered:**
- Force creation of `ALL_MODELS_MARKER` rows with `untested` status — adds complexity for zero benefit on the gateway side.
- TWO separate queries (keys with status + keys without) — less efficient than single LEFT JOIN.

### D4: Full-stream default for all instances (except debug/retry)

**Rationale:** Without per-model routing, the gateway no longer needs to parse request bodies in the hot path. Full-stream mode passes the request body directly to the upstream without buffering, achieving true transparency. Debug mode and retry mode still require buffering (for logging and re-sending, respectively).

**Alternatives considered:**
- Keep buffered mode as default — wastes resources parsing bodies that don't need parsing.
- Add a `streaming_mode: "transparent"` config option — unnecessary; the absence of debug/retry implies transparent.

### D5: `shared_key_status` stays in schema, removed from gateway code

**Rationale:** The user has future plans for this mechanism. Removing it from the schema would create unnecessary diff churn when it's re-added. The gateway no longer reads it; the field remains available for Keeper logic and future use.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Keys without `key_model_status` rows treated as valid by default | Bad keys could be used before Keeper detects them | Fatal statuses (invalid_key, no_access, no_quota) still excluded; Keeper's fast-feedback loop still operates |
| Model name no longer available for gateway metrics/logging | `GATEWAY_ACCESS` log line shows `<all models>` instead of specific model | Log format already handles this via `_format_model_name()`. StreamMonitor uses ALL_MODELS_MARKER. |
| Retry mode iterates over all provider keys instead of per-model subset | Slightly more key rotation on retry | Behavior is semantically correct — all keys are valid for all models in transparent mode |
| Breaking config change requires all operators to restructure YAML | Migration effort for existing deployments | Breaking change documented; example configs updated; minimal restructure needed (rename `models:` → `default_model:`, delete `default_model: "string"` line) |
| Gemini URL-based model parsing retained but non-essential | Dead code in full-stream path | Gemini path parser is zero-overhead (regex on URL, no body read); left in place for future use |

## Migration Plan

1. Merge this change to main branch
2. Operators update their `config/providers.yaml`:
   - Remove `default_model: "model-name"` line
   - Rename `models:` section to `default_model:`
   - Remove `shared_key_status: false` lines (optional, harmless if left)
3. Deploy via `docker-compose up --build -d`
4. No database migration needed (schema unchanged)
5. Rollback: revert to previous commit, restore original config YAML

## Open Questions

- Should `get_all_valid_keys_for_caching()` also exclude `no_model` status? Decision: yes, `no_model` is fatal and should be excluded.
- Should `inspect()` be updated or removed entirely? Decision: update field name for consistency; removal is a separate concern.
