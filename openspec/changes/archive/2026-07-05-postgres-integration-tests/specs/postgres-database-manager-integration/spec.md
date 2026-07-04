## ADDED Requirements

### Requirement: DatabaseManager.initialize_schema creates all tables
The system SHALL verify that `DatabaseManager.initialize_schema()` executes `DB_SCHEMA` against the database and results in all five tables being present.

#### Scenario: initialize_schema creates tables via DatabaseManager
- **WHEN** `db_manager.initialize_schema()` is called
- **THEN** querying `pg_catalog.pg_tables` SHALL show all five tables in the public schema

### Requirement: DatabaseManager.check_connection returns True against live DB
The system SHALL verify that `check_connection()` performs `SELECT 1` and returns `True` when the database is reachable.

#### Scenario: check_connection succeeds against live database
- **WHEN** `db_manager.check_connection()` is called against a running PostgreSQL instance
- **THEN** the method SHALL return `True`

### Requirement: DatabaseManager.wait_for_schema_ready returns immediately when schema exists
The system SHALL verify that `wait_for_schema_ready()` returns without error when the `key_model_status` table already exists.

#### Scenario: Schema-ready returns immediately
- **WHEN** `DB_SCHEMA` has already been executed and the `key_model_status` table exists, and `wait_for_schema_ready(timeout=5)` is called
- **THEN** the method SHALL return promptly without raising `TimeoutError`

### Requirement: DatabaseManager.get_table_health returns health rows for all tables
The system SHALL verify that `get_table_health()` queries `pg_stat_user_tables` and returns a `DatabaseTableHealth` object for each of the five tables in the public schema.

#### Scenario: Health includes all five tables
- **WHEN** `db_manager.get_table_health()` is called
- **THEN** the result SHALL contain five `DatabaseTableHealth` objects with `table_name` matching the five public tables

### Requirement: DatabaseManager.get_table_health computes dead_tuple_ratio
The system SHALL verify that `get_table_health()` returns a valid, non-negative `dead_tuple_ratio` after insert and delete operations create dead tuples.

#### Scenario: Dead tuple ratio is computed after modifications
- **WHEN** a row is inserted into `providers` and then deleted, and `get_table_health()` is called
- **THEN** the `DatabaseTableHealth` object for `"public.providers"` SHALL have `n_dead_tup >= 0`, `n_live_tup >= 0`, and `dead_tuple_ratio >= 0.0`
