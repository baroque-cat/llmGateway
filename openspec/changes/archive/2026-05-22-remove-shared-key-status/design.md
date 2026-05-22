## Context

The `shared_key_status` field in `ProviderConfig` was introduced to optimize health checks for providers with account-level rate limits — where all API keys share a single status rather than having per-model statuses. When enabled, the Keeper checks only one model per key (using `__ALL_MODELS__` marker) instead of individually checking every model.

The transparent proxy gateway change (`2026-05-22-transparent-proxy-gateway`) made the gateway fully transparent: it no longer validates models, no longer selects keys per-model, and no longer reads `shared_key_status`. However, design decision D5 deliberately kept the field in the schema and in `KeyRepository` methods "for future Keeper use."

That future has not materialized. The architecture has moved toward all providers behaving uniformly: one health check per key using the first model from `default_model`, with the result applied to all models for that key. This is exactly the `shared_key_status: true` behavior. The conditional branching in four `KeyRepository` methods now serves no purpose — both branches produce identical behavior because all call-sites already pass `ALL_MODELS_MARKER` as `model_name`.

Additionally, the Prometheus `llm_gateway_keys_total` metric carries a `model` label that is always `"shared"` (transformed from `__ALL_MODELS__`). With all providers using unified key status, this label provides zero information.

## Goals / Non-Goals

**Goals:**
- Remove `shared_key_status` field from `ProviderConfig` Pydantic schema
- Eliminate all conditional branching on `shared_key_status` in `KeyRepository` (4 methods)
- Remove `provider_models` parameter from `KeyRepository.sync()` — it becomes unused when all providers use `__ALL_MODELS__`
- Remove `model` label from `llm_gateway_keys_total` Prometheus metric
- Remove `model` field from `StatusSummaryItem` TypedDict and `get_status_summary()` SQL GROUP BY
- Update all call-sites of `KeyRepository.sync()` to drop `provider_models` argument
- Keep `ALL_MODELS_MARKER` sentinel and `key_model_status.model_name` column as internal implementation detail

**Non-Goals:**
- No changes to `key_model_status` table schema — `model_name TEXT NOT NULL` stays
- No changes to Keeper health-check probe logic — `key_probe.py` already resolves `__ALL_MODELS__` independently
- No changes to gateway — already ignores `shared_key_status`
- No changes to other `KeyRepository` methods (get_all_valid_keys_for_caching, etc.)
- No changes to `get_available_key()` beyond simplifying its branch — it is kept as dead code for potential future use
- No removal of `ALL_MODELS_MARKER` constant or `__ALL_MODELS__` usage

## Decisions

### D1: Unconditional `__ALL_MODELS__` for all providers

**Decision:** All four branching methods in `KeyRepository` (sync, get_keys_to_check, update_status, get_available_key) lose their `if shared_key_status` branches and unconditionally use `__ALL_MODELS__`.

**Rationale:** After the transparent proxy gateway change, all call-sites already pass `ALL_MODELS_MARKER` as `model_name`. Both branches produce identical SQL queries. The branching is cosmetic dead code.

**Alternatives considered:**
- Keep branching with a deprecation warning — adds noise without value; the field is being removed from the schema anyway.
- Remove only the field but keep branching on a hardcoded `True` — defeats the purpose of cleanup.

### D2: Remove `provider_models` from `sync()` signature

**Decision:** Delete `provider_models: list[str]` parameter from `KeyRepository.sync()`. Update both call-sites: `key_sync.py` (removes `provider_models=models_from_config` argument) and `keeper.py` (removes `models_from_config` computation).

**Rationale:** After D1, `sync()` always creates `(key_id, __ALL_MODELS__)` pairs. The `provider_models` list (derived from `default_model.keys()`) is never used inside `sync()`. Keeping an unused parameter is misleading and violates clean code principles.

**Alternatives considered:**
- Keep the parameter with an `_unused` prefix — adds noise; callers still compute and pass the list.
- Remove from call-sites but keep in signature with default `None` — breaks the principle that parameters should be used.

### D3: Remove `model` label from `llm_gateway_keys_total`

**Decision:** Drop the `model` dimension from the Prometheus Gauge. Labels change from `["provider", "model", "status"]` to `["provider", "status"]`. Remove the `__ALL_MODELS__` → `"shared"` transformation in the Prometheus backend.

**Rationale:** After all providers use `__ALL_MODELS__` uniformly, the `model` label always equals `"shared"` — it carries zero information. The meaningful dimensions are provider instance name and status. This aligns with the architectural reality: there are no per-model key statuses; every key has a single status per provider instance.

**Alternatives considered:**
- Keep the label always showing `"shared"` — adds noise to dashboards and queries without any filtering value.
- Rename to `"all"` or `"*"` — cosmetic; still zero information.

### D4: Keep `ALL_MODELS_MARKER` and `key_model_status.model_name` column

**Decision:** Do not remove `ALL_MODELS_MARKER = "__ALL_MODELS__"` constant or the `model_name TEXT NOT NULL` column from the database schema.

**Rationale:** `key_model_status` has a composite PRIMARY KEY `(key_id, model_name)` with `model_name NOT NULL`. Removing the column would require a database migration changing the PK constraint — high risk for zero gain. `ALL_MODELS_MARKER` remains the internal sentinel value populating that column.

### D5: Keep `get_available_key()` but simplify

**Decision:** Simplify the `shared_key_status` branch in `get_available_key()` (always substitute `ALL_MODELS_MARKER`) but keep the method.

**Rationale:** The method is only called from tests — dead code in production. Removing it entirely is a separate concern (dead code elimination). Simplifying its branch maintains consistency with other methods and avoids test breakage.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| YAML configs with `shared_key_status` field fail validation | Operators with custom configs get `ValidationError` on deploy | Documented breaking change; field already removed from example configs; error message from Pydantic is clear |
| First `sync()` cycle deletes old per-model `key_model_status` rows | All per-model health check history is lost | Intentional — new architecture only needs `__ALL_MODELS__` rows; history is transient health data, not audit data |
| `get_keys_to_check()` returns a mix of old per-model and new `__ALL_MODELS__` rows during transition | Deduplication picks first row, which could have arbitrary `model_name` | Add `ORDER BY s.model_name = '__ALL_MODELS__' DESC` to prefer `__ALL_MODELS__` rows; `key_probe.py` resolves any model name anyway |
| Grafana dashboards break when `model` label disappears | Alerting rules or panels filtering by `model` stop working | `model` label has been always `"shared"` since transparent proxy — dashboards already need updates regardless of this change |
| `get_available_key()` simplified but still dead code | Method exists but never called from production | Intentional — kept for potential future use; removing it is a separate task |

## Migration Plan

1. Merge this change to main branch
2. Operators must update `config/providers.yaml`:
   - Remove any `shared_key_status: true` or `shared_key_status: false` lines
   - Field already absent from example configs since transparent-proxy-gateway change
3. Deploy via `docker-compose up --build -d`
4. First Keeper `sync()` cycle automatically removes old per-model `key_model_status` rows and creates `__ALL_MODELS__` rows — no manual DB migration needed
5. Update Grafana dashboards to use only `provider` and `status` labels (remove `model` filter/group-by)
6. Rollback: revert to previous commit, restore original config YAML (if `shared_key_status` was present)

## Open Questions

- Should `get_available_key()` be deleted entirely in a follow-up? It is dead code.
- Should `ALL_MODELS_MARKER` eventually be renamed to something like `UNIFIED_STATUS_MARKER` to better reflect its current purpose? The name is a legacy of when there were actual per-model markers.
