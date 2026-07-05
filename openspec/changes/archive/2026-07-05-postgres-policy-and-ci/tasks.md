## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b test-ref`
- [x] 1.2 Run the full postgres test suite to establish a passing baseline: `bash scripts/run-postgres-tests.sh`

## 2. Block 6 — Policy Enforcement Gatekeeper

- [x] 2.1 Create `tests/test_postgres_policy.py` with module docstring, `_REPO_ROOT`, and path constants
- [x] 2.2 Implement PP1 helper functions: `_function_uses_real_pool`, `_has_postgres_marker`, `_decorator_to_string`
- [x] 2.3 Implement PP1: `test_all_postgres_tests_have_marker` — AST-based scan of `tests/integration/db/test_*.py`, every function using `pg_pool.acquire()` or `db_manager` must have `@pytest.mark.postgres`
- [x] 2.4 Implement PP2: `test_no_mock_pool_in_postgres_tests` — string scan of `tests/integration/db/`, no `MagicMock`, `AsyncMock`, `patch("asyncpg.create_pool")`, `patch("src.db.database.get_pool")`
- [x] 2.5 Implement `_line_index` helper for script analysis
- [x] 2.6 Implement PP3: `test_run_postgres_script_always_starts_fresh` — ≥2 `down -v` calls, lifecycle ordering (pre-down < up --wait < run_group < post-down)
- [x] 2.7 Implement PP4: `test_run_postgres_script_uses_v2_compose` — `podman compose` or `docker compose` (not `docker-compose`), `--wait` (not `sleep`)
- [x] 2.8 Implement PP5: `test_makefile_postgres_target_delegates_to_script` — `bash scripts/run-postgres-tests.sh` present, no inline `poetry run pytest --run-postgres`
- [x] 2.9 Update `tests/test_hardcode_checker_regression.py`: add `"test_postgres_policy.py"` to `_GATEKEEPER_TEST_FILES` list
- [x] 2.10 Run formatting, linting, type checking on `test_postgres_policy.py`: `black`, `ruff check`, `pyright`
- [x] 2.11 Run hardcode checker: `bash scripts/check-test-hardcodes.sh all`
- [x] 2.12 Run policy tests in postgres suite: `poetry run pytest tests/test_postgres_policy.py --run-postgres -v`

## 3. Block 7 — CI Integration

- [x] 3.1 Add `postgres-integration` job to `.github/workflows/quality.yml` after line 140 (end of `gatekeeper` job) — 7 steps: checkout, setup-python 3.13.5, install poetry, install deps, start test-database, run script, teardown with `if: always()`
- [x] 3.2 Configure job trigger: `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`
- [x] 3.3 Update `tests/test_ci_pipeline.py`: add `"postgres-integration"` to `_REQUIRED_JOBS` list
- [x] 3.4 Update `tests/test_ci_pipeline.py`: update docstring for `test_all_four_required_jobs_present` to say "5" instead of "4"
- [x] 3.5 Verify CI pipeline test still passes: `poetry run pytest tests/test_ci_pipeline.py -v`

## 4. Full Verification

- [x] 4.1 Run full postgres suite: `bash scripts/run-postgres-tests.sh`
- [x] 4.2 Run ruff on all changed files
- [x] 4.3 Run pyright on all changed files
- [x] 4.4 Run black --check on all changed files
- [x] 4.5 Run hardcode checker: `bash scripts/check-test-hardcodes.sh all`
