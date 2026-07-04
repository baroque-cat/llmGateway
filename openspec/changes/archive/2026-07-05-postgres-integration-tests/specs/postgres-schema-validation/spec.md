## ADDED Requirements

### Requirement: DB_SCHEMA creates all five tables
The system SHALL verify that `DB_SCHEMA` from `src.db.database` creates exactly five tables — `providers`, `proxies`, `provider_proxy_status`, `api_keys`, `key_model_status` — in the `public` schema of a real PostgreSQL instance.

#### Scenario: Schema creates all tables on first execution
- **WHEN** `DB_SCHEMA` is executed against an empty test database via `asyncpg`
- **THEN** querying `pg_catalog.pg_tables WHERE schemaname = 'public'` SHALL return exactly the five expected table names

### Requirement: DB_SCHEMA is idempotent
The system SHALL verify that executing `DB_SCHEMA` twice does not raise any exceptions and does not alter or remove existing data.

#### Scenario: Second execution does not raise errors
- **WHEN** `DB_SCHEMA` is executed a second time against a database that already has all tables
- **THEN** no exception SHALL be raised

#### Scenario: Second execution preserves existing data
- **WHEN** a row is inserted into the `providers` table and `DB_SCHEMA` is executed a second time
- **THEN** the row count in `providers` SHALL remain unchanged

### Requirement: All six indexes are created
The system SHALL verify that the six `CREATE INDEX IF NOT EXISTS` statements in `DB_SCHEMA` all produce real indexes in the database.

#### Scenario: Indexes exist after schema creation
- **WHEN** `DB_SCHEMA` is executed
- **THEN** querying `pg_indexes WHERE schemaname = 'public'` SHALL return all six index names: `idx_api_keys_provider_id`, `idx_key_model_status_status`, `idx_proxy_status_next_check_time`, `idx_proxy_status_status`, `idx_key_status_next_check_time`, `idx_key_status_gateway_lookup`

### Requirement: Foreign key cascade deletes child rows
The system SHALL verify that deleting a provider row cascades to delete its associated `api_keys` and `key_model_status` rows.

#### Scenario: Deleting provider cascades to keys and status rows
- **WHEN** a provider, an api_key for that provider, and a key_model_status row for that key are inserted, and the provider row is then deleted
- **THEN** querying `api_keys` and `key_model_status` for that provider SHALL return zero rows

### Requirement: Unique constraint on provider name is enforced
The system SHALL verify that inserting a duplicate `providers.name` value raises a unique violation.

#### Scenario: Duplicate provider name raises error
- **WHEN** a provider with `name='test'` is inserted, and a second provider with `name='test'` is inserted
- **THEN** an `asyncpg.UniqueViolationError` SHALL be raised

### Requirement: Composite unique constraint on (provider_id, key_value) is enforced
The system SHALL verify that inserting a duplicate `(provider_id, key_value)` pair in `api_keys` raises a unique violation.

#### Scenario: Duplicate key for same provider raises error
- **WHEN** an api_key with `(provider_id=1, key_value='sk-dup')` is inserted, and a second api_key with the same `(1, 'sk-dup')` is inserted
- **THEN** an `asyncpg.UniqueViolationError` SHALL be raised
