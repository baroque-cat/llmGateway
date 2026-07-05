# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| postgres-policy-gatekeeper | All integration db tests must carry @pytest.mark.postgres | Test function using pg_pool without postgres marker is detected | `tests/test_postgres_policy.py` | `test_all_postgres_tests_have_marker` | policy-tests |
| postgres-policy-gatekeeper | All integration db tests must carry @pytest.mark.postgres | Test function using db_manager fixture without postgres marker is detected | `tests/test_postgres_policy.py` | `test_all_postgres_tests_have_marker` | policy-tests |
| postgres-policy-gatekeeper | All integration db tests must carry @pytest.mark.postgres | Correctly marked test function passes | `tests/test_postgres_policy.py` | `test_all_postgres_tests_have_marker` | policy-tests |
| postgres-policy-gatekeeper | No mock usage in postgres integration tests | File containing MagicMock is detected | `tests/test_postgres_policy.py` | `test_no_mock_pool_in_postgres_tests` | policy-tests |
| postgres-policy-gatekeeper | No mock usage in postgres integration tests | File containing asyncpg pool patch is detected | `tests/test_postgres_policy.py` | `test_no_mock_pool_in_postgres_tests` | policy-tests |
| postgres-policy-gatekeeper | No mock usage in postgres integration tests | Clean file with no mocks passes | `tests/test_postgres_policy.py` | `test_no_mock_pool_in_postgres_tests` | policy-tests |
| postgres-policy-gatekeeper | run-postgres-tests.sh always starts a fresh container | Script has both pre-teardown and post-teardown down -v calls | `tests/test_postgres_policy.py` | `test_run_postgres_script_always_starts_fresh` | policy-tests |
| postgres-policy-gatekeeper | run-postgres-tests.sh always starts a fresh container | Lifecycle ordering is correct | `tests/test_postgres_policy.py` | `test_run_postgres_script_always_starts_fresh` | policy-tests |
| postgres-policy-gatekeeper | run-postgres-tests.sh uses v2 compose syntax | Script uses v2 compose with podman or docker | `tests/test_postgres_policy.py` | `test_run_postgres_script_uses_v2_compose` | policy-tests |
| postgres-policy-gatekeeper | run-postgres-tests.sh uses v2 compose syntax | Script uses --wait not sleep | `tests/test_postgres_policy.py` | `test_run_postgres_script_uses_v2_compose` | policy-tests |
| postgres-policy-gatekeeper | Makefile test-postgres delegates to shell script | Makefile delegates to the script | `tests/test_postgres_policy.py` | `test_makefile_postgres_target_delegates_to_script` | policy-tests |
| postgres-ci-integration | CI workflow has a postgres-integration job | Job runs on schedule and workflow_dispatch only | `tests/test_ci_pipeline.py` | `test_all_four_required_jobs_present` | ci-tests |
| postgres-ci-integration | CI workflow has a postgres-integration job | Job starts test database, runs tests, and tears down | `tests/test_ci_pipeline.py` | `test_all_jobs_run_in_parallel_no_needs` | ci-tests |
| postgres-ci-integration | CI workflow has a postgres-integration job | Job uses the same Python version as other CI jobs | `tests/test_ci_pipeline.py` | `test_all_jobs_run_in_parallel_no_needs` | ci-tests |
| postgres-ci-integration | CI workflow has a postgres-integration job | Job is listed in the required jobs list | `tests/test_ci_pipeline.py` | `test_all_four_required_jobs_present` | ci-tests |
| postgres-ci-integration | Gatekeeper test lists are updated for the new policy file | Policy file is in the gatekeeper regression test list | `tests/test_hardcode_checker_regression.py` | `test_exclude_files_covers_all_gatekeeper_tests` | ci-tests |

## Delegation Groups

### Group: policy-tests

**Scope:** `tests/test_postgres_policy.py` (NEW)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_postgres_policy.py` | 11 (5 test functions) | NEW |

### Group: ci-tests

**Scope:** `.github/workflows/quality.yml`, `tests/test_ci_pipeline.py`, `tests/test_hardcode_checker_regression.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_ci_pipeline.py` | 4 | MODIFY |
| `tests/test_hardcode_checker_regression.py` | 1 | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/test_ci_pipeline.py` | Add `"postgres-integration"` to `_REQUIRED_JOBS` list | New requirement: CI workflow has a postgres-integration job |
| `tests/test_ci_pipeline.py` | Update docstring: "4 required jobs" → "5 required jobs" | Design decision D4: CI job added as Job 5 |
| `tests/test_hardcode_checker_regression.py` | Add `"test_postgres_policy.py"` to `_GATEKEEPER_TEST_FILES` list | New requirement: Gatekeeper test lists are updated for the new policy file |

## Risks & Edge Cases

- **PP1: `ast.unparse()` may miss nested references** → The check uses `ast.unparse(node)` on the entire function body. If `pg_pool.acquire()` is called inside a nested function or lambda, it will still be detected since `unparse` serializes the full subtree. No edge-case risk.
- **PP2: `MagicMock` in comments or docstrings** → String scan may flag comments mentioning `MagicMock` even if it's not imported. Low-impact — such comments are unlikely in integration tests; if they occur, they can be rephrased.
- **CI: test-database container started twice** → CI job starts the container with `up -d --wait`, then `run-postgres-tests.sh` pre-teardowns (`down -v 2>/dev/null || true`) and re-starts it. Redundant but harmless — the script's `--wait` ensures readiness regardless of who started the container.
- **CI: gatekeeper group in run-postgres-tests.sh** → The script's gatekeeper group runs root-level tests with `-m "postgres"`. Only tests marked `@pytest.mark.postgres` are collected. The new policy tests must carry this marker or they won't run.
