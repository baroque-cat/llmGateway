# Configuration System

## Overview

llmGateway uses a **three-tier layered configuration system** that combines a hardcoded base dictionary, user-provided YAML, and Pydantic model validation. The system ensures every configuration key has a safe fallback value while requiring explicit user input for deployment-sensitive parameters (database credentials, API tokens, host/port bindings).

## Architecture

```
config/providers.yaml (user)         .env (environment)
        │                                  │
        ▼                                  ▼
   ruamel.yaml parser              os.environ
        │                                  │
        ▼                                  │
   user_config_raw ────────────────────────┤
        │                                  │
        ▼                                  │
   _resolve_env_vars (pass 1) ◄────────────┘
        │
        ▼
   _build_and_merge_config()
        │
        ├── get_default_config()   ← src/config/defaults.py
        │
        ├── deepmerge(base, user)  ← user always wins
        │
        └── For each provider:
            template "llm_provider_default" from defaults
            → merge user provider config on top
        │
        ▼
   _resolve_env_vars (pass 2)   ← resolves ${VAR} injected from defaults.py
        │
        ▼
   Config.model_validate()      ← Pydantic validation + tier-3 defaults
        │
        ▼
   Config (global singleton via load_config() → _config_instance)
```

## The Three Tiers of Defaults

### Tier 1: `src/config/defaults.py` — Hardcoded Base Dictionary

The function `get_default_config()` returns a fully-structured `dict[str, Any]` with default values for all global sections and a per-provider template (`llm_provider_default`). This dictionary is the **foundation** — it guarantees that every config section exists before user YAML is applied.

**Strategic role of `${ENV_VAR}` placeholders:** The defaults dictionary deliberately contains `${ENV_VAR}` references for operational values:

- `"${DB_HOST}"`, `"${DB_PORT}"`, `"${DB_USER}"`, `"${DB_PASSWORD}"`, `"${DB_NAME}"`
- `"${GATEWAY_HOST}"`, `"${GATEWAY_PORT}"`, `"${GATEWAY_WORKERS}"`
- `"${LLM_PROVIDER_DEFAULT_TOKEN}"`

These are NOT resolved in Tier 1. They are injected as raw strings and resolved later (see "Two-Pass Env Var Resolution" below). If these were hardcoded values instead, the system would silently use unsafe defaults.

**The `llm_provider_default` template:** Inside the `providers` key, there is a special entry `"llm_provider_default"` that serves as a **per-provider template**. It is never treated as a real provider. During loading, each user-defined provider is deep-merged on top of this template, so any provider-level key a user omits falls back to the template's value.

**Known gap:** The `metrics` top-level key is **absent** from `defaults.py` (see comment at line 31). This is covered by Tier 3 (Pydantic `Field(default_factory=MetricsConfig)`). This is documented technical debt.

### Tier 2: User YAML (`config/providers.yaml`)

The user's YAML file is parsed with `ruamel.yaml` (not PyYAML) to preserve `.lc.data` line/column metadata. This metadata is used by the error formatter to report Pydantic validation errors with exact YAML line numbers.

After parsing, the raw dictionary goes through **env var resolution pass 1** (see below). It is then deep-merged on top of the Tier 1 base using `deepmerge.always_merger.merge(base, user)`. User keys always override base keys; missing user keys retain base defaults.

**Provider merging** is handled specially (see `loader.py:132-155`): each user provider entry is merged on top of the `llm_provider_default` template rather than on top of the raw base dict. This prevents one provider's config from leaking into another's.

### Tier 3: Pydantic `Field(default=…)`

After the merged dictionary undergoes env var resolution pass 2, it is passed to `Config.model_validate()`. Pydantic applies its own `Field(default=…)` values for any keys still absent. These are the **last-resort defaults**.

**Important:** Pydantic `Field(default=…)` and Tier 1 (`defaults.py`) values **must be identical** for the same setting. If they diverge, users who omit a section get one value (from Pydantic), while users who include the section but omit a sub-key get another (from `defaults.py` via deepmerge). See "Consistency Contract" below.

## Two-Pass Environment Variable Resolution

The loader (`src/config/loader.py:90-117`) performs **two separate passes** of `${ENV_VAR}` resolution:

### Pass 1 (line 67): User YAML
Resolves `${VAR}` placeholders in the user's raw YAML dict. This pass happens **before** merging with defaults, so only variables explicitly written in the user's YAML are resolved here.

### Pass 2 (line 74): Merged Config
Resolves `${VAR}` placeholders that were **injected from `defaults.py`** during the merge. Since these were not present in the user's YAML, pass 1 could not resolve them. This second pass is what makes the `${DB_HOST}` etc. placeholders in `defaults.py` actually work.

### Resolution Rules

The pattern is `^\$\{(?P<name>[A-Z0-9_]+)\}$` — only exact, all-uppercase matches are resolved:

- `"${DB_HOST}"` → `os.environ["DB_HOST"]` (resolved)
- `"prefix-${VAR}"` → NOT resolved (partial match)
- `"${lowercase}"` → NOT resolved (uppercase-only)
- Unset env var → `ValueError` with clear message

## Pydantic Model Hierarchy

All config models live in `src/config/schemas.py` (27 models total). They use **composition over inheritance** — every model extends `BaseModel` directly, with nesting expressed through field types:

```
Config (root)                              →  YAML root
├── LoggingConfig                          →  logging:
│   └── HttpClientLoggingConfig            →    http_client:
├── HttpClientConfig                       →  http_client:
│   └── HttpClientPoolConfig               →    pool:
├── MetricsConfig                          →  metrics:
├── GatewayConfig                          →  gateway:
├── KeeperConfig                           →  keeper:
├── DatabaseConfig                         →  database:
│   ├── DatabasePoolConfig                 →    pool:
│   ├── DatabaseRetryConfig                →    retry:
│   └── VacuumPolicyConfig                 →    vacuum_policy:
└── dict[str, ProviderConfig]              →  providers:
    └── <provider_name>:                   →    <provider_name>:
        └── ProviderConfig (fields):
            ├── dict[str, ModelInfo]       →      default_model:
            ├── AccessControlConfig        →      access_control:
            ├── ProxyConfig                 →      proxy_config:
            ├── TimeoutConfig              →      timeouts:
            ├── ErrorParsingConfig         →      error_parsing:
            │   └── list[ErrorParsingRule] →        rules:
            ├── HealthPolicyConfig         →      worker_health_policy:
            │   ├── AdaptiveBatchingConfig →        adaptive_batching:
            │   └── PurgeConfig            →        purge:
            ├── KeyExportConfig            →      key_export:
            │   └── KeyInventoryConfig     →        inventory:
            └── GatewayPolicyConfig        →      gateway_policy:
                └── RetryPolicyConfig      →        retry:
                    ├── RetryOnErrorConfig →          on_key_error:
                    └── RetryOnErrorConfig →          on_server_error:
```

### Key Models

| Model | Purpose |
|---|---|
| `Config` | Root model. 7 top-level sections. Validates token uniqueness, provider names, pool sizing. |
| `ProviderConfig` | One provider instance. 12 sub-configs. `provider_type` is the only **required** field. |
| `HealthPolicyConfig` | Keeper's probe scheduling, retry intervals, quarantine policy, adaptive batching. 17 fields. |
| `AdaptiveBatchingConfig` | Self-tuning batch controller parameters. 13 fields. Has `to_params()` bridge to `AdaptiveBatchingParams` dataclass in `src/core/models.py`. |
| `ErrorParsingConfig` | Pattern-based error reclassification rules. Used to distinguish e.g. 400→NO_QUOTA from 400→INVALID_KEY. |
| `DatabaseConfig` | PostgreSQL connection, pool sizing, retry policy, vacuum policy. Has `to_dsn()` helper. |

### Validation

10 of 27 models have `extra="forbid"` (including all provider-facing models the user edits), preventing unrecognized YAML keys from being silently ignored. Cross-field validators enforce invariants like:

- `RetryPolicyConfig`: if `enabled=true`, at least one retry path must have `attempts >= 1`
- `AdaptiveBatchingConfig`: `min < max` for bounds, start values within bounds
- `HealthPolicyConfig`: quarantine/purge logical ordering, verification timeout
- `ProxyConfig`: `static_url` required when `mode="static"`
- `Config`: unique `gateway_access_token` per providr, pool sizing <= 97

## Configuration Loading Flow

### Entry Point

`src.config.load_config(path) → Config` (defined in `__init__.py:31`)

This is the **only** function that should be called to load configuration. It:
1. Creates a `ConfigLoader(path)`
2. Calls `loader.load()`
3. Stores the result in the module-level singleton `_config_instance`
4. Returns the `Config` object

Consumers access the loaded config via:
- `src.config.get_config() → Config` — direct access to the Pydantic model
- `src.core.ConfigAccessor` — Facade with domain-specific accessor methods

### Loader Steps (in `loader.py:46-88`)

1. `load_dotenv()` — load `.env` into `os.environ`
2. Parse YAML with `ruamel.yaml.YAML()` → raw dict with `.lc.data` metadata
3. First-pass env var resolution on user dict
4. Deep merge: `defaults.py` base + user dict (with special provider template logic)
5. Second-pass env var resolution on merged dict (resolves injected defaults.py `${VAR}`s)
6. `Config.model_validate()` — Pydantic coercion, validation, tier-3 defaults
7. On `ValidationError`: format error with YAML line numbers via `error_formatter.py`, print to stderr, `sys.exit(1)`

## Public API

| Symbol | Type | Source | Purpose |
|---|---|---|---|
| `load_config(path)` | Function | `src.config.__init__` | Bootstrap: load, validate, cache |
| `get_config()` | Function | `src.config.__init__` | Retrieve cached singleton, raise if not loaded |
| `Config` | Pydantic model | `src.config.schemas` | Root configuration object |
| `ConfigLoader` | Class | `src.config.loader` | Orchestrator (rarely used directly) |

**Notable non-exports:**
- `ConfigAccessor` — lives in `src.core.accessor`, imported from there
- `setup_logging()` — lives in `src.config.logging_config`, imported directly by `main.py` and `keeper.py`
- `get_default_config()` — internal implementation detail, only used by `loader.py` and tests

## The Example Config File

`config/example_full_config.yaml` is the canonical reference for all available settings. The `gemini-production` provider instance (lines 80–200) is the **full exemplar** — it populates every optional section (`key_export`, `error_parsing`, all 13 `adaptive_batching` fields, `purge`, etc.). The other three providers (`deepseek-main`, `anthropic-production`, `qwen-home`) intentionally omit sections to demonstrate default-fallback behavior.

See `config/example_full_config.yaml` for the complete reference.

## Consistency Contract: `defaults.py` ↔ `schemas.py`

The values in `defaults.py` (Tier 1) and Pydantic `Field(default=…)` in `schemas.py` (Tier 3) **must match** for the same configuration key. If they diverge:

- Users who **omit a section** get the Pydantic default (Tier 3)
- Users who **include the section but omit a sub-key** get the `defaults.py` value (Tier 1, via deepmerge)

This produces different runtime behavior for semantically equivalent config omissions.

### Known Divergences

Currently, `AdaptiveBatchingConfig` has a latent inconsistency (see plan in internal tracker). All other keys are aligned.

## ENV Vars

All `${ENV_VAR}` placeholders in both the user YAML and `defaults.py` are resolved from `os.environ` (loaded from `.env` via `python-dotenv`). Unset variables cause a `ValueError` at startup. See `.env.example` for the required variables.

## Related Documentation

- `docs/ERRORS.md` — ErrorReason classification: fatal vs retryable vs client errors
- `docs/ERROR_PARSING.md` — Error parsing config: pattern-based error reclassification
- `docs/DEBUG_MODE.md` — Gateway debug modes: disabled, no_content, full_body
- `config/example_full_config.yaml` — Annotated reference with all available settings
- `src/config/schemas.py` — All Pydantic models with docstrings and validators
