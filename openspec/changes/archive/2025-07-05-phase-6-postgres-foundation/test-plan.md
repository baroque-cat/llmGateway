# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script detects podman or docker engine | `tests/test_postgres_runner.py` | `test_script_detects_podman_first_then_docker` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script tears down any existing container before starting | `tests/test_postgres_runner.py` | `test_pre_teardown_uses_down_v_with_error_suppression` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script starts a fresh test-database container | `tests/test_postgres_runner.py` | `test_uses_up_dash_dash_wait_test_database` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script starts a fresh test-database container (no sleep) | `tests/test_postgres_runner.py` | `test_no_sleep_used_for_readiness` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script starts a fresh test-database container (not production) | `tests/test_postgres_runner.py` | `test_targets_test_database_not_database_service` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script runs postgres tests in groups | `tests/test_postgres_runner.py` | `test_run_group_handles_exit_code_5_as_non_failure` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script runs postgres tests in groups (failure) | `tests/test_postgres_runner.py` | `test_run_group_handles_exit_code_nonzero_as_failure` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script always tears down after tests complete | `tests/test_postgres_runner.py` | `test_post_teardown_uses_down_v_without_error_suppression` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script always tears down after tests complete (ordering) | `tests/test_postgres_runner.py` | `test_teardown_ordering_pre_down_before_up_before_test_before_post_down` | postgres-runner-gatekeeper |
| postgres-test-runner | Container lifecycle script manages PostgreSQL test runs | Script uses v2 compose syntax | `tests/test_postgres_runner.py` | `test_uses_v2_compose_syntax_not_v1` | postgres-runner-gatekeeper |
| postgres-test-runner | Makefile delegates postgres tests to the lifecycle script | test-postgres target delegates to script | `tests/test_postgres_runner.py` | `test_makefile_test_postgres_delegates_to_script` | postgres-runner-gatekeeper |
| test-infra-polish | Metrics keeper test is relocated to tests/unit/metrics/ | test_keeper_metrics.py is in the metrics directory | `tests/test_test_infra_polish.py` | `test_keeper_metrics_file_is_in_metrics_dir` | infra-polish |
| test-infra-polish | Metrics keeper test is relocated to tests/unit/metrics/ | test_keeper_metrics.py is in the metrics directory (not in services) | `tests/test_test_infra_polish.py` | `test_keeper_metrics_file_not_in_services_dir` | infra-polish |
| test-infra-polish | Metrics keeper test is relocated to tests/unit/metrics/ | mock_run_keeper_dependencies fixture is accessible from both subtrees | `tests/test_test_infra_polish.py` | `test_mock_run_keeper_fixture_in_unit_conftest` | infra-polish |
| test-infra-polish | Makefile has standalone gatekeeper and boundary targets | test-gatekeeper runs root-level tests only | `tests/test_test_infra_polish.py` | `test_makefile_has_test_gatekeeper_target` | infra-polish |
| test-infra-polish | Makefile has standalone gatekeeper and boundary targets | test-boundary runs a single file fast check | `tests/test_test_infra_polish.py` | `test_makefile_has_test_boundary_target` | infra-polish |
| test-infra-polish | tests/integration/db/ directory exists as scaffold | Directory structure exists | `tests/test_test_infra_polish.py` | `test_integration_db_dir_exists` | infra-polish |
| test-infra-polish | tests/integration/db/ directory exists as scaffold | Directory structure exists (init.py) | `tests/test_test_infra_polish.py` | `test_integration_db_has_init_file` | infra-polish |
| gatekeeper-hardcode-checker | BANNED_OTHER_REGEX includes non-canonical DB password pattern | Non-canonical DB password in source is detected | `tests/test_hardcode_checker_patterns.py` | `test_banned_regex_database_config_password` | gatekeeper-patterns |
| gatekeeper-hardcode-checker | BANNED_OTHER_REGEX includes httpcore version enforcement pattern | Non-canonical httpcore version is detected | `tests/test_hardcode_checker_patterns.py` | `test_banned_regex_httpcore_version` | gatekeeper-patterns |
| gatekeeper-hardcode-checker | EXCLUDE_FILES includes future postgres policy test | test_postgres_policy.py is excluded from scanning | `tests/test_hardcode_checker_patterns.py` | `test_exclude_files_contains_test_postgres_policy` | gatekeeper-patterns |

## Delegation Groups

### Group: postgres-runner-gatekeeper

**Scope:** `tests/test_postgres_runner.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_postgres_runner.py` | 11 | NEW |

### Group: infra-polish

**Scope:** `tests/test_test_infra_polish.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_test_infra_polish.py` | 7 | NEW |

### Group: gatekeeper-patterns

**Scope:** `tests/test_hardcode_checker_patterns.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_hardcode_checker_patterns.py` | 3 | MODIFY |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/test_hardcode_checker_patterns.py` | Add 3 new tests for the 2 new BANNED_OTHER_REGEX patterns and the new EXCLUDE_FILES entry | New requirements: "Non-canonical DB password in source is detected", "Non-canonical httpcore version is detected", "test_postgres_policy.py is excluded from scanning" |

## Risks & Edge Cases

- **Moving mock_run_keeper_dependencies breaks other tests in tests/unit/services/** → Covered by infra-polish test `test_mock_run_keeper_fixture_in_unit_conftest` which verifies the fixture is defined in the correct location; existing `pytest tests/unit/services/` pass validates no breakage.
- **run-postgres-tests.sh fails on systems without docker compose v2 plugin** → Covered by postgres-runner-gatekeeper test `test_script_detects_podman_first_then_docker` which verifies both engine checks exist and the graceful exit 0 path.
- **--wait flag not supported in older docker-compose versions** → Covered by postgres-runner-gatekeeper test `test_uses_up_dash_dash_wait_test_database` which verifies `--wait` is present in the script.
- **test-database port 5433 conflicts with another local PostgreSQL instance** → Not covered by gatekeeper tests (runtime environment concern). Mitigated by non-standard port selection.
- **New BANNED_OTHER_REGEX patterns produce false positives** → Covered by running `bash scripts/check-test-hardcodes.sh all` after adding patterns; the canonical file-level gatekeeper tests (`test_hardcode_checker_regression.py`) will catch false positives on the clean codebase.
