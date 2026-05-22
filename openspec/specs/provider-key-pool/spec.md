# provider-key-pool

## Purpose

Defines the behavior of the gateway's in-memory API key pool. Key pools are indexed
solely by provider instance name, enabling transparent proxy operation where any valid
key for a provider can service any model request. This replaces the previous per-model
pool indexing and removes `shared_key_status` logic from the gateway cache.

## Requirements

### Requirement: Key pools are indexed by provider name only
The gateway cache SHALL index API key pools using the provider instance name as the sole pool key. No model name SHALL be included in the pool key.

#### Scenario: Pool key is provider name
- **WHEN** `refresh_key_pool()` processes valid key records from the database
- **THEN** each key SHALL be placed into a pool identified by `provider_name` only
- **AND** the pool key format SHALL NOT include `:{model_name}` or `:{ALL_MODELS_MARKER}` suffixes

#### Scenario: Multiple models share one pool
- **WHEN** a provider has 3 valid keys with `model_name` values `"gpt-4"`, `"gpt-4"`, and `"__ALL_MODELS__"`
- **THEN** all 3 keys SHALL be placed into the same pool identified by the provider name

### Requirement: get_key_from_pool accepts provider_name only
`get_key_from_pool()` SHALL accept a single `provider_name` argument and SHALL NOT accept a `model_name` argument. It SHALL return any available key from the provider's pool using round-robin rotation.

#### Scenario: Key retrieved without model name
- **WHEN** `get_key_from_pool("my-provider")` is called
- **THEN** the method SHALL return a `(key_id, key_value)` tuple from the pool keyed by `"my-provider"`
- **AND** the key SHALL be rotated to the back of the deque

#### Scenario: No valid keys available
- **WHEN** `get_key_from_pool("my-provider")` is called and the pool is empty
- **THEN** the method SHALL return `None`

### Requirement: remove_key_from_pool accepts provider_name and key_id only
`remove_key_from_pool()` SHALL accept `provider_name` and `key_id` arguments and SHALL NOT accept a `model_name` argument. It SHALL remove the specified key from the provider's pool.

#### Scenario: Key removed from provider pool
- **WHEN** `remove_key_from_pool("my-provider", key_id=42)` is called
- **THEN** the key with `key_id=42` SHALL be removed from the pool keyed by `"my-provider"`
- **AND** the pool size SHALL decrease by 1

### Requirement: Gateway cache ignores shared_key_status config
The gateway cache SHALL NOT read `provider_config.shared_key_status` for any purpose. All providers SHALL be treated uniformly with per-provider key pools.

#### Scenario: shared_key_status has no effect on pool selection
- **WHEN** a provider has `shared_key_status: true` or `shared_key_status: false`
- **THEN** `get_key_from_pool()` and `remove_key_from_pool()` SHALL behave identically for both cases
- **AND** no code path in `gateway_cache.py` SHALL access `provider_config.shared_key_status`

### Requirement: Keys without key_model_status rows are included in cache
The database query in `get_all_valid_keys_for_caching()` SHALL include API keys that have no corresponding row in the `key_model_status` table, treating them as valid by default.

#### Scenario: Key without status row is cached
- **WHEN** an API key exists in `api_keys` but has no row in `key_model_status` (e.g., no models configured)
- **THEN** `get_all_valid_keys_for_caching()` SHALL return that key with `model_name = '__ALL_MODELS__'`
- **AND** the key SHALL be available in the gateway cache

#### Scenario: Key with fatal status is excluded
- **WHEN** an API key has a `key_model_status` row with `status IN ('invalid_key', 'no_access', 'no_quota', 'no_model')`
- **THEN** `get_all_valid_keys_for_caching()` SHALL NOT return that key
