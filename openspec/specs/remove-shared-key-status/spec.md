# remove-shared-key-status

## Purpose

Remove the `shared_key_status` field from `ProviderConfig` and eliminate all conditional branching
based on it in `KeyRepository` methods. All providers uniformly use `__ALL_MODELS__` for key-model
associations, making every provider behave as if `shared_key_status` were always true.

## Requirements

### Requirement: ProviderConfig excludes shared_key_status field
The `ProviderConfig` Pydantic model SHALL NOT contain a `shared_key_status` field. Configuration YAML files containing `shared_key_status` SHALL fail validation.

#### Scenario: shared_key_status field is absent from schema
- **WHEN** the `ProviderConfig` Pydantic model is inspected
- **THEN** no `shared_key_status` field SHALL exist on the model
- **AND** YAML files containing `shared_key_status: true` or `shared_key_status: false` SHALL raise `ValidationError`

#### Scenario: Default config is valid without shared_key_status
- **WHEN** a minimal `ProviderConfig` is constructed with only required fields
- **THEN** validation SHALL succeed without any `shared_key_status` value

### Requirement: sync() unconditionally uses ALL_MODELS_MARKER
`KeyRepository.sync()` SHALL create key-model associations using `__ALL_MODELS__` for all providers, regardless of any legacy `shared_key_status` setting. It SHALL NOT read `provider_config.shared_key_status`.

#### Scenario: sync creates ALL_MODELS_MARKER associations for any provider
- **WHEN** `sync()` is called for any enabled provider with 3 keys
- **THEN** the desired model state SHALL be `{(key_id_1, "__ALL_MODELS__"), (key_id_2, "__ALL_MODELS__"), (key_id_3, "__ALL_MODELS__")}`
- **AND** no individual model associations SHALL be created

#### Scenario: sync removes legacy per-model rows
- **WHEN** `sync()` encounters existing per-model `key_model_status` rows like `(key_id, "gpt-4")` and `(key_id, "gpt-4o")`
- **THEN** those per-model rows SHALL be removed via DELETE
- **AND** new `(key_id, "__ALL_MODELS__")` rows SHALL be inserted

### Requirement: sync() does not accept provider_models parameter
`KeyRepository.sync()` SHALL NOT have a `provider_models` parameter. Call-sites SHALL NOT compute or pass `models_from_config` to `sync()`.

#### Scenario: sync() signature excludes provider_models
- **WHEN** the `KeyRepository.sync()` method signature is inspected
- **THEN** the signature SHALL be `(self, provider_name, provider_id, keys_from_file)`
- **AND** no `provider_models: list[str]` parameter SHALL be present

#### Scenario: Call-sites do not pass provider_models
- **WHEN** `key_sync.py` calls `db_manager.keys.sync()`
- **THEN** the call SHALL NOT include a `provider_models=` keyword argument

### Requirement: get_keys_to_check() deduplicates for all providers
`KeyRepository.get_keys_to_check()` SHALL return at most one `KeyToCheck` per `key_id` for all providers. It SHALL NOT check `provider_config.shared_key_status`.

#### Scenario: Multiple model rows deduplicated to one per key
- **WHEN** `get_keys_to_check()` queries the database and returns 3 rows for `key_id=42` with different `model_name` values
- **THEN** the method SHALL return only one `KeyToCheck` for `key_id=42`
- **AND** the deduplication SHALL apply uniformly to all enabled providers

#### Scenario: ALL_MODELS_MARKER rows preferred during deduplication
- **WHEN** `get_keys_to_check()` result contains both `(key_id, "__ALL_MODELS__")` and `(key_id, "gpt-4")` rows
- **THEN** the `__ALL_MODELS__` row SHALL be selected over per-model rows due to `ORDER BY`

### Requirement: update_status() always queries by ALL_MODELS_MARKER
`KeyRepository.update_status()` SHALL use `WHERE model_name = '__ALL_MODELS__'` for all providers. It SHALL NOT check `provider_config.shared_key_status`.

#### Scenario: Status update uses ALL_MODELS_MARKER in WHERE clause
- **WHEN** `update_status()` is called for any provider and any key
- **THEN** the SQL WHERE clause SHALL be `key_id = $7 AND model_name = $8` with `$8 = '__ALL_MODELS__'`

### Requirement: get_available_key() always substitutes ALL_MODELS_MARKER
`KeyRepository.get_available_key()` SHALL substitute `__ALL_MODELS__` as `actual_model_name` for all providers. It SHALL NOT check `provider_config.shared_key_status`.

#### Scenario: Model name always substituted to ALL_MODELS_MARKER
- **WHEN** `get_available_key(provider_name, "any-model")` is called
- **THEN** the SQL query SHALL use `$2 = '__ALL_MODELS__'` as the model name parameter
