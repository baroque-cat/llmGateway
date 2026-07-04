# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| postgres-schema-validation | DB_SCHEMA creates all five tables | Schema creates all tables on first execution | `tests/integration/db/test_schema.py` | `test_schema_creates_all_five_tables` | schema-tests |
| postgres-schema-validation | DB_SCHEMA is idempotent | Second execution does not raise errors | `tests/integration/db/test_schema.py` | `test_schema_idempotent_second_run` | schema-tests |
| postgres-schema-validation | DB_SCHEMA is idempotent | Second execution preserves existing data | `tests/integration/db/test_schema.py` | `test_schema_idempotent_preserves_data` | schema-tests |
| postgres-schema-validation | All six indexes are created | Indexes exist after schema creation | `tests/integration/db/test_schema.py` | `test_all_six_indexes_created` | schema-tests |
| postgres-schema-validation | Foreign key cascade deletes child rows | Deleting provider cascades to keys and status rows | `tests/integration/db/test_schema.py` | `test_foreign_key_cascade_provider_to_keys` | schema-tests |
| postgres-schema-validation | Unique constraint on provider name is enforced | Duplicate provider name raises error | `tests/integration/db/test_schema.py` | `test_unique_constraint_provider_name` | schema-tests |
| postgres-schema-validation | Composite unique constraint on (provider_id, key_value) is enforced | Duplicate key for same provider raises error | `tests/integration/db/test_schema.py` | `test_unique_constraint_provider_id_key_value` | schema-tests |
| postgres-repository-integration | ProviderRepository.sync inserts new providers | Sync inserts new provider names | `tests/integration/db/test_provider_repository.py` | `test_sync_inserts_new_providers` | repository-tests |
| postgres-repository-integration | ProviderRepository.sync deletes removed providers via KeyPurger | Removed provider is deleted with cascade | `tests/integration/db/test_provider_repository.py` | `test_sync_deletes_removed_providers` | repository-tests |
| postgres-repository-integration | ProviderRepository.sync is atomic | Add and delete in single sync call | `tests/integration/db/test_provider_repository.py` | `test_sync_add_and_delete_in_single_transaction` | repository-tests |
| postgres-repository-integration | ProviderRepository.get_id_map returns correct mapping | Id map reflects synced providers | `tests/integration/db/test_provider_repository.py` | `test_get_id_map_returns_correct_mapping` | repository-tests |
| postgres-repository-integration | KeyRepository.sync inserts new keys and ALL_MODELS_MARKER status rows | Sync inserts keys with ALL_MODELS marker | `tests/integration/db/test_key_repository.py` | `test_sync_inserts_new_keys` | repository-tests |
| postgres-repository-integration | KeyRepository.sync is add-only | Second sync with same keys does not duplicate | `tests/integration/db/test_key_repository.py` | `test_sync_no_duplicate_keys_on_rerun` | repository-tests |
| postgres-repository-integration | KeyRepository.sync removes stale per-model status associations | Stale model association is cleaned up | `tests/integration/db/test_key_repository.py` | `test_sync_removes_stale_model_associations` | repository-tests |
| postgres-repository-integration | KeyRepository.update_status manages failing_since correctly | First failure sets failing_since | `tests/integration/db/test_key_repository.py` | `test_update_status_failing_since_logic` | repository-tests |
| postgres-repository-integration | KeyRepository.update_status manages failing_since correctly | Second failure preserves original failing_since | `tests/integration/db/test_key_repository.py` | `test_update_status_failing_since_logic` | repository-tests |
| postgres-repository-integration | KeyRepository.update_status manages failing_since correctly | Success resets failing_since to NULL | `tests/integration/db/test_key_repository.py` | `test_update_status_failing_since_logic` | repository-tests |
| postgres-repository-integration | KeyRepository.update_status targets ALL_MODELS_MARKER | update_status writes to ALL_MODELS row when passed a specific model name | `tests/integration/db/test_key_repository.py` | `test_update_status_all_models_marker_substitution` | repository-tests |
| postgres-repository-integration | KeyRepository.get_keys_to_check respects next_check_time filter | Only overdue keys are returned | `tests/integration/db/test_key_repository.py` | `test_get_keys_to_check_time_filter` | repository-tests |
| postgres-repository-integration | KeyRepository.get_available_key returns random selection | Multiple calls return different keys | `tests/integration/db/test_key_repository.py` | `test_get_available_key_random_selection` | repository-tests |
| postgres-repository-integration | KeyRepository.get_all_valid_keys_for_caching includes keys without status rows | Untracked key is included in cache list | `tests/integration/db/test_key_repository.py` | `test_get_all_valid_keys_for_caching_includes_untested` | repository-tests |
| postgres-repository-integration | KeyRepository.get_all_valid_keys_for_caching excludes fatal status keys | Key with fatal status is excluded from cache | `tests/integration/db/test_key_repository.py` | `test_get_all_valid_keys_for_caching_excludes_fatal_status` | repository-tests |
| postgres-database-manager-integration | DatabaseManager.initialize_schema creates all tables | initialize_schema creates tables via DatabaseManager | `tests/integration/db/test_database_manager.py` | `test_initialize_schema_creates_all_tables` | manager-tests |
| postgres-database-manager-integration | DatabaseManager.check_connection returns True against live DB | check_connection succeeds against live database | `tests/integration/db/test_database_manager.py` | `test_check_connection_returns_true` | manager-tests |
| postgres-database-manager-integration | DatabaseManager.wait_for_schema_ready returns immediately when schema exists | Schema-ready returns immediately | `tests/integration/db/test_database_manager.py` | `test_wait_for_schema_ready_returns_immediately` | manager-tests |
| postgres-database-manager-integration | DatabaseManager.get_table_health returns health rows for all tables | Health includes all five tables | `tests/integration/db/test_database_manager.py` | `test_get_table_health_returns_all_tables` | manager-tests |
| postgres-database-manager-integration | DatabaseManager.get_table_health computes dead_tuple_ratio | Dead tuple ratio is computed after modifications | `tests/integration/db/test_database_manager.py` | `test_get_table_health_dead_tuple_ratio` | manager-tests |

## Delegation Groups

### Group: schema-tests

**Scope:** `tests/integration/db/test_schema.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/integration/db/test_schema.py` | 7 | NEW |

### Group: repository-tests

**Scope:** `tests/integration/db/test_provider_repository.py`, `tests/integration/db/test_key_repository.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/integration/db/test_provider_repository.py` | 4 | NEW |
| `tests/integration/db/test_key_repository.py` | 11 scenarios (10 tests) | NEW |

### Group: manager-tests

**Scope:** `tests/integration/db/test_database_manager.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/integration/db/test_database_manager.py` | 5 | NEW |

### Group: gap-04-fix

**Scope:** `scripts/check-test-hardcodes.sh`

| Test File | Scenarios | Action |
|---|---|---|
| `scripts/check-test-hardcodes.sh` | 1 line change | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `scripts/check-test-hardcodes.sh` | Add `"test_postgres_policy.py"` to EXCLUDE_FILES array after line 141 | Gap 0.4 from original blueprint: pre-register Block 6 policy test file to prevent false positives in hardcode checker |

## Risks & Edge Cases

- **KR5 timestamp fidelity** → The three-phase `failing_since` test uses `datetime.now(timezone.utc)` for initial setup and reads back from `asyncpg`. PostgreSQL TIMESTAMPTZ has microsecond precision; Python's `assert row["failing_since"] == first_failing` relies on the same `datetime` object returned by the first DB read. The test SHALL read `first_failing` from the database after the first `update_status` call (not from Python local) to ensure the comparison is against the DB-stored value.
- **KR3 empty-state edge case** → `KeyRepository.sync` dynamically builds a WHERE clause for stale model removal. If there are zero keys after sync, the DELETE is still safe (no rows to delete). The test does not need to cover the zero-key case explicitly — it's a no-op path.
- **DM5 autovacuum interference** → `autovacuum` may clear dead tuples between INSERT+DELETE and the `get_table_health()` query. Assert `>= 0` not `> 0`. The test validates method structure and return type, not absolute dead tuple count.
- **S4 index name drift** → If `DB_SCHEMA` index names change, S4 will fail. This is the desired behavior — the test catches DDL drift. The 6 index names SHALL be hardcoded in the test assertion as the canonical reference.
