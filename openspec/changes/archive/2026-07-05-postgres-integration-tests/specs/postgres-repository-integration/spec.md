## ADDED Requirements

### Requirement: ProviderRepository.sync inserts new providers
The system SHALL verify that `ProviderRepository.sync(provider_names, db_manager)` inserts rows into the `providers` table for each name in `provider_names` that does not already exist.

#### Scenario: Sync inserts new provider names
- **WHEN** `sync(["p1", "p2"])` is called on an empty database
- **THEN** querying `SELECT name FROM providers ORDER BY name` SHALL return `["p1", "p2"]`

### Requirement: ProviderRepository.sync deletes removed providers via KeyPurger
The system SHALL verify that `ProviderRepository.sync` delegates deletion of providers no longer in the config to `KeyPurger.purge_provider`, and that this cascades to remove associated `api_keys`.

#### Scenario: Removed provider is deleted with cascade
- **WHEN** a provider "old_prov" with an associated api_key exists, and `sync(["new_prov"])` is called
- **THEN** "old_prov" SHALL be absent from the `providers` table AND its api_key SHALL be absent from the `api_keys` table

### Requirement: ProviderRepository.sync is atomic (add + delete in single transaction)
The system SHALL verify that a `sync()` call that both adds and removes providers in a single invocation produces an atomic result — both changes applied or neither.

#### Scenario: Add and delete in single sync call
- **WHEN** a provider "old" pre-exists, and `sync(["new"])` is called
- **THEN** "new" SHALL be present in `providers` AND "old" SHALL be absent

### Requirement: ProviderRepository.get_id_map returns correct mapping
The system SHALL verify that `get_id_map()` returns a `dict[str, int]` mapping all provider names to their database IDs.

#### Scenario: Id map reflects synced providers
- **WHEN** `sync(["a", "b"])` is called
- **THEN** `get_id_map()` SHALL return `{"a": <id_a>, "b": <id_b>}` where `<id_a>` and `<id_b>` are valid integer primary keys

### Requirement: KeyRepository.sync inserts new keys and ALL_MODELS_MARKER status rows
The system SHALL verify that `KeyRepository.sync(provider_name, provider_id, keys_from_file)` inserts rows into `api_keys` and creates corresponding `key_model_status` rows with `model_name = '__ALL_MODELS__'` and `status = 'untested'`.

#### Scenario: Sync inserts keys with ALL_MODELS marker
- **WHEN** a provider exists and `sync(name, id, {"sk-a", "sk-b"})` is called
- **THEN** `api_keys` SHALL contain 2 rows AND `key_model_status` SHALL contain 2 rows, both with `model_name = '__ALL_MODELS__'` and `status = 'untested'`

### Requirement: KeyRepository.sync is add-only (no duplicate keys on re-run)
The system SHALL verify that calling `sync()` twice with the same keys does not create duplicate rows.

#### Scenario: Second sync with same keys does not duplicate
- **WHEN** `sync()` is called with `{"sk-a"}` twice
- **THEN** the `api_keys` table SHALL contain exactly 1 row for `"sk-a"`

### Requirement: KeyRepository.sync removes stale per-model status associations
The system SHALL verify that `sync()` removes `key_model_status` rows for model names other than `__ALL_MODELS__` that were previously associated with a key.

#### Scenario: Stale model association is cleaned up
- **WHEN** a key has two `key_model_status` rows: `('__ALL_MODELS__', 'untested')` and `('gpt-4', 'untested')`, and `sync()` is called
- **THEN** only the `('__ALL_MODELS__', 'untested')` row SHALL remain; the `('gpt-4', 'untested')` row SHALL be deleted

### Requirement: KeyRepository.update_status manages failing_since correctly
The system SHALL verify the `failing_since` state machine in `update_status`: (1) first failure sets `failing_since` to a timestamp, (2) subsequent failures preserve the original `failing_since` value, (3) a successful result resets `failing_since` to NULL.

#### Scenario: First failure sets failing_since
- **WHEN** a key has `status = 'untested'` and `failing_since = NULL`, and `update_status()` is called with a failed `CheckResult`
- **THEN** `failing_since` SHALL be set to a non-NULL timestamp AND `status` SHALL be set to the error reason value

#### Scenario: Second failure preserves original failing_since
- **WHEN** `update_status()` is called a second time with another failed `CheckResult`
- **THEN** `failing_since` SHALL remain equal to the timestamp set by the first failure (not overwritten with a newer timestamp)

#### Scenario: Success resets failing_since to NULL
- **WHEN** `update_status()` is called with a successful `CheckResult` (`ok=True`)
- **THEN** `failing_since` SHALL be reset to NULL AND `status` SHALL be set to `'valid'`

### Requirement: KeyRepository.update_status targets ALL_MODELS_MARKER regardless of model_name argument
The system SHALL verify that `update_status(key_id, model_name, ...)` always writes to the `key_model_status` row with `model_name = '__ALL_MODELS__'`, regardless of the `model_name` argument value.

#### Scenario: update_status writes to ALL_MODELS row when passed a specific model name
- **WHEN** a key_model_status row exists with `model_name = '__ALL_MODELS__'` and `status = 'untested'`, and `update_status(key_id, "gpt-4", ...)` is called with a successful `CheckResult`
- **THEN** the `__ALL_MODELS__` row SHALL be updated to `status = 'valid'` AND no new row with `model_name = 'gpt-4'` SHALL be created

### Requirement: KeyRepository.get_keys_to_check respects next_check_time filter
The system SHALL verify that `get_keys_to_check()` only returns keys whose `next_check_time` is in the past.

#### Scenario: Only overdue keys are returned
- **WHEN** two keys exist: one with `next_check_time = NOW() - 1 hour` and another with `next_check_time = NOW() + 1 hour`
- **THEN** `get_keys_to_check()` SHALL return only the first key

### Requirement: KeyRepository.get_available_key returns random selection
The system SHALL verify that `get_available_key()` returns different keys across multiple calls when multiple valid keys exist.

#### Scenario: Multiple calls return different keys
- **WHEN** 5 valid keys exist for a provider, and `get_available_key()` is called 10 times
- **THEN** the set of returned key_ids SHALL contain at least 2 distinct values (random OFFSET produces variation)

### Requirement: KeyRepository.get_all_valid_keys_for_caching includes keys without status rows
The system SHALL verify that `get_all_valid_keys_for_caching()` includes keys that have no corresponding `key_model_status` row (LEFT JOIN with NULL status).

#### Scenario: Untracked key is included in cache list
- **WHEN** a key exists in `api_keys` but has no row in `key_model_status`
- **THEN** `get_all_valid_keys_for_caching()` SHALL include that key in the result

### Requirement: KeyRepository.get_all_valid_keys_for_caching excludes fatal status keys
The system SHALL verify that `get_all_valid_keys_for_caching()` excludes keys whose `key_model_status.status` is one of the fatal values: `'invalid_key'`, `'no_access'`, `'no_quota'`, `'no_model'`.

#### Scenario: Key with fatal status is excluded from cache
- **WHEN** a key exists in `api_keys` with a `key_model_status` row having `status = 'invalid_key'`
- **THEN** `get_all_valid_keys_for_caching()` SHALL NOT include that key in the result
