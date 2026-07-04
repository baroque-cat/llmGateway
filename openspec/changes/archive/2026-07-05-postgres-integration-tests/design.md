## Context

llmGateway uses PostgreSQL 18 with raw asyncpg (no ORM) for its five-table data model: `providers`, `proxies`, `provider_proxy_status`, `api_keys`, `key_model_status`. The `DB_SCHEMA` string in `src/db/database.py` defines DDL with `CREATE TABLE IF NOT EXISTS` and 6 `CREATE INDEX IF NOT EXISTS` statements. All foreign keys use `ON DELETE CASCADE`.

The existing test suite (120 files) exclusively uses `unittest.mock` — `MagicMock`, `AsyncMock`, `patch` — to mock asyncpg at the Python boundary. No test has ever executed a real SQL query against PostgreSQL. This means:

- DDL regressions (typo in CREATE TABLE, wrong FK target, missing index) pass the test suite
- The `failing_since` state machine (`CASE WHEN $6 THEN NULL ELSE COALESCE(failing_since, NOW()) END`) has never been tested with a real database round-trip
- `ProviderRepository.sync`'s atomicity (transaction wrapping INSERT + DELETE via KeyPurger) has never been validated against a real `ROLLBACK`

Blocks 1 and 2 (infrastructure) are already complete:
- `scripts/run-postgres-tests.sh` — container lifecycle script (podman-first, up --wait, teardown -v)
- `tests/integration/db/conftest.py` — fixtures: `pg_pool` (session-scoped asyncpg pool on port 5433), `_ensure_schema` (autouse TRUNCATE in FK-safe order), `db_manager` (monkeypatches `get_pool()`)
- `tests/integration/db/test_smoke.py` — 3 smoke tests confirming fixtures work

Block 0.4 gap: `test_postgres_policy.py` is not pre-registered in `scripts/check-test-hardcodes.sh` EXCLUDE_FILES, which would cause false positives when Block 6 is implemented later.

## Goals / Non-Goals

**Goals:**
- Add 26 integration tests that exercise the database layer against real PostgreSQL
- Verify DDL correctness: table creation, indexes, FK cascade, UNIQUE constraints
- Verify repository CRUD operations: `ProviderRepository` (4 tests), `KeyRepository` (10 tests)
- Verify `DatabaseManager` facade: initialization, health checks, `pg_stat_user_tables` stats (5 tests)
- Close the 0.4 gap by pre-registering `test_postgres_policy.py` in hardcode checker exclusions
- All tests marked `@pytest.mark.postgres` and runnable via `bash scripts/run-postgres-tests.sh`

**Non-Goals:**
- No production code changes in `src/`
- No tests for `ProxyRepository` (its `sync()` is a no-op stub)
- No tests for `KeyPurger.purge_stopped_keys` (requires scheduler integration)
- No CI pipeline changes (deferred to Block 7)
- No gatekeeper policy tests (deferred to Block 6)

## Decisions

### D1: Use existing `db_manager` fixture from Block 2 for DatabaseManager tests; build KeyRepository/ProviderRepository directly from `pg_pool` for repository tests

**Rationale:** The `db_manager` fixture (from `tests/integration/db/conftest.py`) monkeypatches `get_pool()` and constructs a full `DatabaseManager`. This is correct for Block 5 tests that exercise `DatabaseManager` methods. For Block 4 repository tests, constructing `KeyRepository(pg_pool)` or `ProviderRepository(pg_pool, mock_key_purger)` directly gives finer-grained control over the SUT without the `DatabaseManager` indirection. This is the same pattern used by `test_smoke.py` tests which use `pg_pool` directly for pool-level assertions.

**Alternatives considered:** Using `db_manager.providers` / `db_manager.keys` everywhere. Rejected because: (a) it entangles repository tests with `KeyPurger` behavior, (b) the `db_manager` fixture creates a fresh `KeyPurger` per test which adds noise, (c) direct construction is cleaner for isolated SUT testing.

### D2: Use manual INSERT/DELETE via `pg_pool.acquire()` for test data setup instead of repository methods

**Rationale:** Tests should not use the SUT to set up the SUT's own preconditions. For example, KR5 (failing_since logic) needs a pre-existing `key_model_status` row with `status='untested'` — using `KeyRepository.sync()` to create it would couple the test to `sync()` behavior. Manual SQL avoids this.

**Alternatives considered:** Using repository methods for setup. Rejected because it creates false coupling — if `sync()` breaks, all downstream tests that depend on it would also break, masking the real failure.

### D3: Use `_TEARDOWN_ORDER` from conftest for fixture-driven cleanup; accept that `autovacuum` may clear dead tuples before `get_table_health()` queries them

**Rationale:** The `_ensure_schema` autouse fixture already truncates all 5 tables in FK-safe order after every test. For DM5 (dead tuple ratio), `autovacuum` on a freshly-started container may clear dead tuples before the assertion runs. The test asserts `>= 0` rather than `> 0` to handle this non-determinism. This is a well-known limitation of `pg_stat_user_tables` in integration tests.

### D4: Pre-register `test_postgres_policy.py` in EXCLUDE_FILES now, even though the file does not exist yet

**Rationale:** Block 0.4 from the original blueprint requires this pre-registration. The `check-test-hardcodes.sh` gatekeeper scans all test files for banned patterns. `test_postgres_policy.py` (Block 6) will contain banned patterns as test assertions (e.g., `"docker compose"`, `"--wait"`). Pre-registering avoids future gatekeeper failures when Block 6 is implemented. The hardcode checker treats EXCLUDE_FILES entries for non-existent files as no-ops, so adding it now is safe.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| **KR5 flakiness from timestamp comparisons** | Timestamp `failing_since` assertions use exact `==` comparison between two `datetime` objects from the same Python process — no timezone ambiguity. | All timestamps use `datetime.now(timezone.utc)`. The three calls in KR5 execute sequentially in a single test function, so `first_failing == row["failing_since"]` is deterministic. |
| **KR3 dynamic WHERE clause edge case** | `KeyRepository.sync` builds a parameterized `WHERE (key_id=$N AND model_name=$N+1) OR ...` clause dynamically. An empty desired-state (no keys after sync) would produce invalid SQL. | The test only verifies stale removal with existing keys; the empty-state edge case is a production concern (conductor wouldn't call sync for a provider with zero keys). |
| **DM5 dead tuples zeroed by autovacuum** | `autovacuum` may run between INSERT+DELETE and `get_table_health()`, clearing dead tuples. | Assert `>= 0` not `> 0`. Test validates the method returns a well-formed `DatabaseTableHealth` object, not that dead tuples exist. |
| **S4: index name mismatch** | If `DB_SCHEMA` is refactored and index names change, S4 will fail — but this is the desired behavior (it's a schema validation test). | Low risk — index names are stable and this test is exactly what catches DDL drift. |
| **S5: CASCADE only tested for DELETE, not UPDATE** | FK constraints define `ON DELETE CASCADE` but not `ON UPDATE CASCADE` — provider `id` is SERIAL and never updated. | No risk — the SERIAL PK is never modified in application code. |
| **0.4 gap: missing pre-registration** | `check-test-hardcodes.sh` will flag `test_postgres_policy.py` as containing banned patterns when Block 6 is added. | Pre-register now (part of this change). |

## Open Questions

- **Q1**: Should `ProviderRepository.sync`'s `copy_records_to_table` use be tested explicitly? The function is an asyncpg built-in; its correctness is assumed. Current plan does not test it separately — it's implicitly covered by PR1 (inserts happen).

- **Q2**: Should we add a test that `KeyPurger.purge_provider` is called with correct arguments during `ProviderRepository.sync`? This would require mocking `KeyPurger` even in integration tests, mixing mock and real DB patterns. Current plan: this is tested in unit tests (`test_provider_repository.py`); integration tests focus on SQL-level correctness.
