## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `test-ref`
- [x] 1.2 Verify all existing tests pass before starting: `make test` and `make typecheck` and `make lint`

## 2. Gap Fix — Block 0.4 (Pre-register test_postgres_policy.py)

- [x] 2.1 Add `"test_postgres_policy.py"` to EXCLUDE_FILES array in `scripts/check-test-hardcodes.sh` (after line 141, before the pre-existing violations comment block at line 142)
- [x] 2.2 Verify hardcode checker still passes: `bash scripts/check-test-hardcodes.sh all`

## 3. Block 3 — Schema Validation Tests

- [x] 3.1 Create `tests/integration/db/test_schema.py` with 7 tests per `specs/postgres-schema-validation/spec.md`
- [x] 3.2 Implement S1: `test_schema_creates_all_five_tables` — query `pg_catalog.pg_tables`, assert 5 table names
- [x] 3.3 Implement S2: `test_schema_idempotent_second_run` — execute DB_SCHEMA twice, assert no exception
- [x] 3.4 Implement S3: `test_schema_idempotent_preserves_data` — INSERT, re-execute DB_SCHEMA, assert row count unchanged
- [x] 3.5 Implement S4: `test_all_six_indexes_created` — query `pg_indexes`, assert all 6 index names present
- [x] 3.6 Implement S5: `test_foreign_key_cascade_provider_to_keys` — INSERT provider+key+status, DELETE provider, assert 0 rows in all 3 tables
- [x] 3.7 Implement S6: `test_unique_constraint_provider_name` — duplicate INSERT, assert `UniqueViolationError`
- [x] 3.8 Implement S7: `test_unique_constraint_provider_id_key_value` — duplicate (provider_id, key_value), assert `UniqueViolationError`
- [x] 3.9 Run schema tests: `poetry run pytest tests/integration/db/test_schema.py -v --run-postgres -m "postgres"`

## 4. Block 4 — Repository Integration Tests

### 4.1 ProviderRepository

- [x] 4.1a Create `tests/integration/db/test_provider_repository.py`
- [x] 4.1b Implement PR1: `test_sync_inserts_new_providers` — sync(["p1","p2"]), assert both in providers table
- [x] 4.1c Implement PR2: `test_sync_deletes_removed_providers` — pre-insert "old" with key, sync(["new"]), assert "old" and its keys deleted
- [x] 4.1d Implement PR3: `test_sync_add_and_delete_in_single_transaction` — pre-insert "old", sync(["new"]), assert "old" deleted AND "new" inserted
- [x] 4.1e Implement PR4: `test_get_id_map_returns_correct_mapping` — sync(["a","b"]), get_id_map(), assert {"a": <id>, "b": <id>}
- [x] 4.1f Run provider repo tests: `poetry run pytest tests/integration/db/test_provider_repository.py -v --run-postgres -m "postgres"`

### 4.2 KeyRepository

- [x] 4.2a Create `tests/integration/db/test_key_repository.py` with setup helper `_setup_provider_with_key`
- [x] 4.2b Implement KR1: `test_sync_inserts_new_keys` — create provider, sync keys, assert 2 api_keys + 2 key_model_status rows with `__ALL_MODELS__`
- [x] 4.2c Implement KR2: `test_sync_no_duplicate_keys_on_rerun` — sync twice, assert no duplicate rows
- [x] 4.2d Implement KR3: `test_sync_removes_stale_model_associations` — create key with 2 status rows (ALL_MODELS + "test-model"), sync, assert only ALL_MODELS remains
- [x] 4.2e Implement KR4: `test_sync_all_models_marker_association` — sync 3 keys, assert all KMS rows have `model_name='__ALL_MODELS__'` and `status='untested'`
- [x] 4.2f Implement KR5: `test_update_status_failing_since_logic` — 3-phase test: (1) fail sets failing_since, (2) fail preserves it, (3) success resets to NULL. Read `first_failing` from DB after first call for precise comparison
- [x] 4.2g Implement KR6: `test_update_status_all_models_marker_substitution` — update_status with model_name="test-model", assert `__ALL_MODELS__` row was updated, no new row created
- [x] 4.2h Implement KR7: `test_get_keys_to_check_time_filter` — two keys with past/future next_check_time, assert only past key returned
- [x] 4.2i Implement KR8: `test_get_available_key_random_selection` — 5 valid keys, call 10 times, assert >= 2 distinct key_ids
- [x] 4.2j Implement KR9: `test_get_all_valid_keys_for_caching_includes_untested` — key without key_model_status row, assert included in result
- [x] 4.2k Implement KR10: `test_get_all_valid_keys_for_caching_excludes_fatal_status` — key with status='invalid_key', assert excluded from result
- [x] 4.2l Run key repo tests: `poetry run pytest tests/integration/db/test_key_repository.py -v --run-postgres -m "postgres"`

## 5. Block 5 — DatabaseManager Integration Tests

- [x] 5.1 Create `tests/integration/db/test_database_manager.py`
- [x] 5.2 Implement DM1: `test_initialize_schema_creates_all_tables` — call `db_manager.initialize_schema()`, assert 5 tables in pg_tables
- [x] 5.3 Implement DM2: `test_check_connection_returns_true` — call `db_manager.check_connection()`, assert `True`
- [x] 5.4 Implement DM3: `test_wait_for_schema_ready_returns_immediately` — schema exists, `wait_for_schema_ready(timeout=5)`, assert no TimeoutError
- [x] 5.5 Implement DM4: `test_get_table_health_returns_all_tables` — call `get_table_health()`, assert 5 DatabaseTableHealth objects with correct names
- [x] 5.6 Implement DM5: `test_get_table_health_dead_tuple_ratio` — INSERT+DELETE, call `get_table_health()`, assert `dead_tuple_ratio >= 0.0`
- [x] 5.7 Run manager tests: `poetry run pytest tests/integration/db/test_database_manager.py -v --run-postgres -m "postgres"`

## 6. Full Integration Suite Verification

- [x] 6.1 Run full postgres suite via script: `bash scripts/run-postgres-tests.sh`
- [x] 6.2 Run linter on new files: `poetry run ruff check tests/integration/db/test_schema.py tests/integration/db/test_provider_repository.py tests/integration/db/test_key_repository.py tests/integration/db/test_database_manager.py`
- [x] 6.3 Run type checker: `poetry run pyright tests/integration/db/`
- [x] 6.4 Run hardcode checker: `bash scripts/check-test-hardcodes.sh all` — must exit 0
- [x] 6.5 Run formatter: `poetry run black tests/integration/db/`
