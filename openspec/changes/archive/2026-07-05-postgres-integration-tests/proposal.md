## Why

llmGateway currently has zero integration tests that exercise its database layer (PostgreSQL 18, raw asyncpg, no ORM) against a real database instance. All 120 existing tests are pure unit tests that mock asyncpg at the `MagicMock` boundary — they verify parameter-passing and SQL fragments but never validate actual DDL correctness, constraint enforcement, FK cascade behavior, or the critical `failing_since` state machine in `KeyRepository.update_status`. This blind spot means a DDL regression (wrong index, missing CASCADE, broken COALESCE) would pass the entire test suite and only surface in production. The copium project has already proven this pattern with a similar test suite; porting it now closes the highest-risk gap in llmGateway's quality coverage.

## What Changes

- **New**: 26 PostgreSQL integration tests across 3 new files in `tests/integration/db/`, validated against a real `test-database` Docker container (port 5433)
- **New**: `test_schema.py` — 7 tests verifying DDL correctness: table creation, index presence, idempotency, FK cascade, UNIQUE constraints
- **New**: `test_provider_repository.py` — 4 tests for `ProviderRepository.sync` (insert, delete, atomic add+delete, id-map)
- **New**: `test_key_repository.py` — 10 tests for all 6 `KeyRepository` methods including the critical 3-phase `failing_since` state machine test
- **New**: `test_database_manager.py` — 5 tests for `DatabaseManager` initialization, health checks, and `pg_stat_user_tables` dead-tuple tracking
- **Fix**: Pre-register `test_postgres_policy.py` in `scripts/check-test-hardcodes.sh` EXCLUDE_FILES (gap 0.4 from the original blueprint)
- **No production code changes** — tests exercise existing `src/db/database.py` against real asyncpg

## Capabilities

### New Capabilities
- `postgres-schema-validation`: Verify that DB_SCHEMA DDL produces 5 tables, 6 indexes, correct FK cascades, and UNIQUE constraints against a real PostgreSQL 18 instance
- `postgres-repository-integration`: Verify that `ProviderRepository` and `KeyRepository` correctly read and write data through real asyncpg, including the critical `failing_since` state-machine logic in `update_status`
- `postgres-database-manager-integration`: Verify that `DatabaseManager.initialize_schema`, `check_connection`, `wait_for_schema_ready`, and `get_table_health` work correctly against a real database

### Modified Capabilities
<!-- No existing specs are modified — this is purely additive test coverage -->

## Impact

- **New files**: `tests/integration/db/test_schema.py`, `tests/integration/db/test_provider_repository.py`, `tests/integration/db/test_key_repository.py`, `tests/integration/db/test_database_manager.py`
- **Modified files**: `scripts/check-test-hardcodes.sh` (add `test_postgres_policy.py` to EXCLUDE_FILES)
- **No changes** to `src/` production code
- **Dependencies**: Existing fixtures from `tests/integration/db/conftest.py` (Block 2 — already complete), existing `scripts/run-postgres-tests.sh` (Block 1 — already complete), Docker `test-database` service from `docker-compose.yml`
- **CI impact**: Postgres tests run only via `make test-postgres` / `bash scripts/run-postgres-tests.sh` (not in the regular CI pipeline on every push; scheduled/manual only per Block 7)
