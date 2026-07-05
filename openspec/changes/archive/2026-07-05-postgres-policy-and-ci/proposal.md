## Why

Blocks 0–5 of the postgres integration test suite are complete: 26 tests across 4 files validate DDL, repository CRUD, and `DatabaseManager` facade against real PostgreSQL 18. However, this test suite has no governance mechanism to prevent regression — no tests verify that new postgres tests carry the correct `@pytest.mark.postgres` marker, no tests block mock usage in integration tests, and no CI job runs the suite on a schedule. Blocks 6 and 7 close these gaps: a policy-enforcement gatekeeper (5 tests) and a nightly CI job.

## What Changes

- **New**: `tests/test_postgres_policy.py` — 5 policy enforcement tests (PP1–PP5) that validate postgres integration test policy:
  - PP1 (AST-based): Every test in `tests/integration/db/` that uses `pg_pool.acquire()` or `db_manager` must have `@pytest.mark.postgres`
  - PP2 (string scan): No `patch("asyncpg.create_pool")`, `patch("src.db.database.get_pool")`, `MagicMock`, or `AsyncMock` in `tests/integration/db/`
  - PP3 (script analysis): `run-postgres-tests.sh` always starts fresh — ≥2 `down -v` calls, teardown order verified
  - PP4 (string scan): Script uses v2 compose syntax (`podman compose` / `docker compose`), `--wait` not `sleep`
  - PP5 (Makefile scan): `test-postgres` target delegates to `bash scripts/run-postgres-tests.sh`, no inline pytest
- **New**: `.github/workflows/quality.yml` — `postgres-integration` job (Job 5), runs on `schedule` (03:00 UTC daily) and `workflow_dispatch`
- **Modified**: `tests/test_hardcode_checker_regression.py` — add `test_postgres_policy.py` to `_GATEKEEPER_TEST_FILES` list
- **Modified**: `tests/test_ci_pipeline.py` — add `postgres-integration` to `_REQUIRED_JOBS` list

## Capabilities

### New Capabilities
- `postgres-policy-gatekeeper`: 5 structural tests enforcing integration test policies (marker compliance, mock prohibition, script lifecycle, compose syntax, Makefile delegation)
- `postgres-ci-integration`: Nightly CI job (`postgres-integration`) running the full postgres integration suite on schedule and manual dispatch

### Modified Capabilities
<!-- No existing spec requirements change — only implementation constant lists are updated -->

## Impact

- **New files**: `tests/test_postgres_policy.py`
- **Modified files**: `.github/workflows/quality.yml`, `tests/test_ci_pipeline.py`, `tests/test_hardcode_checker_regression.py`
- **No changes** to `src/` production code
- **No changes** to existing `tests/integration/db/` test files
- **CI impact**: New `postgres-integration` job runs on schedule + manual dispatch only (not on every push); uses `docker compose` in GitHub Actions runner
- **Test infrastructure**: `@pytest.mark.postgres` on root-level policy tests — collected by `run-postgres-tests.sh` gatekeeper group, excluded from `make test` G5 group
