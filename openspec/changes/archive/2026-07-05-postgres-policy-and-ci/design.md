## Context

Blocks 0–5 of the PostgreSQL integration test suite are complete: 26 tests across 4 files. The test infrastructure is operational — `run-postgres-tests.sh` manages container lifecycle, `conftest.py` provides fixtures, and all tests run against a real PostgreSQL 18 instance on port 5433. The existing gatekeeper ecosystem includes 25 root-level gatekeeper tests (G5), an AST-based layer import scanner (`test_layer_import_scan.py`), a hardcode pattern checker (`scripts/check-test-hardcodes.sh`), and a CI workflow with 4 parallel jobs (`quality.yml`).

Two gaps remain: (1) no automated enforcement of postgres test policies (marker compliance, mock prohibition, script integrity), and (2) the postgres test suite runs only manually via `make test-postgres` — it has no scheduled CI job.

## Goals / Non-Goals

**Goals:**
- Add 5 policy enforcement tests (`test_postgres_policy.py`) that validate: marker compliance (PP1), mock prohibition (PP2), script lifecycle freshness (PP3), v2 compose syntax (PP4), Makefile delegation (PP5)
- Add `@pytest.mark.postgres` to all 5 tests so they are collected by `run-postgres-tests.sh` gatekeeper group
- Add `postgres-integration` CI job to `quality.yml` — runs on `schedule` (03:00 UTC daily) and `workflow_dispatch`
- Update `test_hardcode_checker_regression.py` EXCLUDE_FILES coverage test
- Update `test_ci_pipeline.py` `_REQUIRED_JOBS` list

**Non-Goals:**
- No production code changes in `src/`
- No changes to existing `tests/integration/db/` test files
- No new pytest markers (existing `postgres` marker is sufficient)
- No CI job that runs on every push (postgres tests are ~10 min with container startup)
- No modification to `run-postgres-tests.sh` (it already has a gatekeeper group)

## Decisions

### D1: Use `@pytest.mark.postgres` on root-level policy tests, not `@pytest.mark.meta`

**Rationale:** `run-postgres-tests.sh` gatekeeper group (line 75) runs `poetry run pytest ... -m "postgres"`, so only `@pytest.mark.postgres` tests are collected. The `meta` marker is documented but never actually used in any test file. Using `postgres` follows the existing pattern in `test_postgres_runner.py` (already marks root-level tests with `@pytest.mark.postgres`). These policy tests do not connect to a database — they only scan files — but the marker is necessary for collection by the gatekeeper group.

**Trade-off:** Regular `make test` G5 excludes `-m "not postgres"`, so these tests will NOT run on every push. This is intentional — they are governance checks for the postgres test suite, not for general code changes.

### D2: PP1 uses `ast.parse()` + `ast.unparse()` for decorator detection, not regex

**Rationale:** Detecting `@pytest.mark.postgres` via regex is fragile — decorators can span multiple lines, contain comments, or be chained (`@pytest.mark.postgres\n@pytest.mark.asyncio`). AST parsing is deterministic and handles all valid Python syntax. The existing `test_layer_import_scan.py` already uses `ast.walk()` for import scanning — PP1 follows the same pattern.

**Alternatives considered:** Regex on raw source text. Rejected: fragile, false positives on commented-out decorators, false negatives on multi-line decorators.

### D3: PP2 uses plain string scan (not AST) to detect banned imports

**Rationale:** Mock usage in postgres tests is a categorical violation — any occurrence of `patch("asyncpg`, `MagicMock`, or `AsyncMock` in `tests/integration/db/` is a failure. String scan is fast, simple, and catches all cases (including imports, inline usage, and string-based references). AST parsing would only detect runtime imports, missing comments, docstrings, and conditional blocks.

### D4: CI job runs `docker compose` directly, not `podman compose`

**Rationale:** GitHub Actions runners use Docker, not Podman. The `run-postgres-tests.sh` script is podman-first for local development, but in CI the engine detection falls through to docker. The CI job starts the database container explicitly before calling the script to ensure the container is ready; the script's own `up -d --wait` is idempotent (redundant but harmless).

### D5: PP5 (Makefile test) is distinct from existing `test_postgres_runner.py::test_makefile_test_postgres_delegates_to_script`

**Rationale:** The existing test (`test_postgres_runner.py:210-218`) validates that the Makefile delegates. PP5 additionally validates that the Makefile does NOT contain `poetry run pytest --run-postgres` (inline pytest call). This negative assertion is unique to PP5.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| **PP1: `ast.unparse()` availability** | `ast.unparse()` was added in Python 3.9 — llmGateway requires 3.13.5+, safe | No risk |
| **PP1: tests using `db_manager` parameter without `pg_pool.acquire()`** | A test that takes `db_manager` fixture but never calls `pg_pool.acquire()` is still flagged by PP1 | Acceptable — `db_manager` implies real DB usage via `get_pool()`, marker is still required |
| **PP2: string scan false positives on comments** | A comment mentioning `MagicMock` or `AsyncMock` in an allowed context (e.g., docstring explaining why mocking is NOT used) would trigger PP2 | Low impact — such comments are unlikely in integration tests. If they occur, they can be rephrased |
| **PP1+PP2 break if `test_postgres_policy.py` itself is scanned** | PP1 scans `tests/integration/db/test_*.py` only, not root-level files. PP2 also scans only `tests/integration/db/`. Both scoped to the integration test directory | No self-scan risk |
| **CI: run-postgres-tests.sh pre-teardown conflicts** | The CI job starts `test-database` with `up -d --wait`, then the script tears it down with `down -v` and re-starts it | Script's pre-teardown `2>/dev/null || true` is error-suppressed — safe even if the CI-started container is running |
| **test_ci_pipeline.py breaks** | Adding a 5th job makes `test_all_four_required_jobs_present` fail | Updated `_REQUIRED_JOBS` list in the same commit |

## Open Questions

- **Q1**: Should PP1 also check for `@pytest.mark.asyncio(loop_scope="session")` on postgres tests? Current scope: only checks `@pytest.mark.postgres` because `pg_pool` fixture is session-scoped and asyncpg operations require `loop_scope="session"`. Decision deferred — adding a second decorator check would be a separate, smaller task.
