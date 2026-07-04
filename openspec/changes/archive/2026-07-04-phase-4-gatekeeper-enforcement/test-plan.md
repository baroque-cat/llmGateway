# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| S1 | synthetic-checker-tests | Tier 2 synthetic tests | Canonical mode detects banned patterns | tests/test_hardcode_checker_core.py | test_canonical_detects_banned_production_url | checker-core |
| S2 | synthetic-checker-tests | Tier 2 synthetic tests | Canonical mode detects banned patterns | tests/test_hardcode_checker_core.py | test_canonical_detects_banned_secret | checker-core |
| S3 | synthetic-checker-tests | Tier 2 synthetic tests | Canonical mode detects banned patterns | tests/test_hardcode_checker_core.py | test_canonical_detects_banned_db_param | checker-core |
| S4 | synthetic-checker-tests | Tier 2 synthetic tests | Canonical mode detects banned patterns | tests/test_hardcode_checker_core.py | test_canonical_detects_banned_model | checker-core |
| S5 | synthetic-checker-tests | Tier 2 synthetic tests | Canonical mode detects banned patterns | tests/test_hardcode_checker_core.py | test_canonical_detects_banned_provider_type | checker-core |
| S6 | synthetic-checker-tests | Tier 2 synthetic tests | Boundary allows with annotation | tests/test_hardcode_checker_core.py | test_boundary_allows_with_annotation | checker-core |
| S7 | synthetic-checker-tests | Tier 2 synthetic tests | Boundary rejects without annotation | tests/test_hardcode_checker_core.py | test_boundary_rejects_without_annotation | checker-core |
| S8 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned | tests/test_hardcode_checker_core.py | test_production_url_always_banned_boundary | checker-core |
| S9 | synthetic-checker-tests | Tier 2 synthetic tests | Root mode detects banned patterns | tests/test_hardcode_checker_core.py | test_root_detects_banned_model | checker-core |
| S10 | synthetic-checker-tests | Tier 2 synthetic tests | All mode composes results | tests/test_hardcode_checker_core.py | test_all_mode_composition | checker-core |
| S11 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_canonical_detects_production_url | checker-urls |
| S12 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_boundary_detects_production_url | checker-urls |
| S13 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_boundary_rejects_url_even_with_annotation | checker-urls |
| S14 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_root_detects_production_url | checker-urls |
| S15 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_all_mode_detects_url_in_canonical_dir | checker-urls |
| S16 | synthetic-checker-tests | Tier 2 synthetic tests | Production URLs always banned (all modes) | tests/test_hardcode_checker_production_urls.py | test_all_urls_in_banned_list_detected | checker-urls |
| S17 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_all_mode_passes_on_clean_codebase | checker-regression |
| S18 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_canonical_mode_passes | checker-regression |
| S19 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_boundary_mode_passes | checker-regression |
| S20 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_root_mode_passes | checker-regression |
| S21 | synthetic-checker-tests | Regression tests | Checker output deterministic | tests/test_hardcode_checker_regression.py | test_output_consistent_across_runs | checker-regression |
| S22 | synthetic-checker-tests | Regression tests | No-args equals all mode | tests/test_hardcode_checker_regression.py | test_no_args_equals_all_mode | checker-regression |
| S23 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_summary_line_present_on_success | checker-regression |
| S24 | synthetic-checker-tests | Regression tests | Clean codebase zero violations | tests/test_hardcode_checker_regression.py | test_exclude_files_covers_all_gatekeeper_tests | checker-regression |
| S25 | synthetic-checker-tests | Boundary compliance | Boundary mode passes clean | tests/test_boundary_compliance.py | test_boundary_mode_passes_on_clean_codebase | checker-boundary |
| S26 | synthetic-checker-tests | Boundary compliance | Boundary files have annotations | tests/test_boundary_compliance.py | test_boundary_files_have_annotations | checker-boundary |
| S27 | synthetic-checker-tests | Boundary compliance | Removing annotation triggers error | tests/test_boundary_compliance.py | test_removing_annotation_triggers_violation | checker-boundary |
| S28 | synthetic-checker-tests | Boundary compliance | Pre-commit hook valid | tests/test_boundary_compliance.py | test_precommit_hook_exists | checker-boundary |
| S29 | synthetic-checker-tests | Boundary compliance | Pre-commit hook valid | tests/test_boundary_compliance.py | test_precommit_hook_entry_correct | checker-boundary |
| S30 | synthetic-checker-tests | Boundary compliance | Pre-commit hook valid | tests/test_boundary_compliance.py | test_precommit_hook_files_pattern | checker-boundary |
| S31 | synthetic-checker-tests | Boundary compliance | Pre-commit hook valid | tests/test_boundary_compliance.py | test_precommit_hook_pass_filenames_false | checker-boundary |
| S32 | synthetic-checker-tests | Boundary compliance | CI contains gatekeeper job | tests/test_boundary_compliance.py | test_ci_has_gatekeeper_job | checker-boundary |
| S33 | synthetic-checker-tests | Boundary compliance | CI contains gatekeeper job | tests/test_boundary_compliance.py | test_ci_gatekeeper_runs_checker_script | checker-boundary |
| S34 | synthetic-checker-tests | Boundary compliance | CI contains gatekeeper job | tests/test_boundary_compliance.py | test_ci_gatekeeper_runs_g5_tests | checker-boundary |
| S35 | synthetic-checker-tests | Cache fixture meta-tests | Hash covers script content | tests/test_conftest_checker_cache.py | test_hash_covers_script_content | checker-cache-expand |
| S36 | synthetic-checker-tests | Cache fixture meta-tests | Hash covers scanned test files | tests/test_conftest_checker_cache.py | test_hash_covers_scanned_test_files | checker-cache-expand |
| S37 | synthetic-checker-tests | Cache fixture meta-tests | Hash excludes __pycache__ | tests/test_conftest_checker_cache.py | test_hash_excludes_pycache | checker-cache-expand |
| S38 | synthetic-checker-tests | Cache fixture meta-tests | Hash is deterministic | tests/test_conftest_checker_cache.py | test_hash_deterministic | checker-cache-expand |
| S39 | synthetic-checker-tests | Cache fixture meta-tests | Hash within sub-second budget | tests/test_conftest_checker_cache.py | test_hash_within_subsecond_budget | checker-cache-expand |
| S40 | synthetic-checker-tests | Cache fixture meta-tests | Cache startup within budget | tests/test_conftest_checker_cache.py | test_cache_startup_within_budget | checker-cache-expand |
| S41 | synthetic-checker-tests | Cache fixture meta-tests | All mode matches direct subprocess | tests/test_conftest_checker_cache.py | test_checker_result_all_matches_direct_subprocess | checker-cache-expand |
| S42 | pre-commit-hook | Pre-commit blocks hardcoded values | ban-test-hardcodes runs authoritatively | tests/test_boundary_compliance.py | test_precommit_hook_exists | checker-boundary |
| S43 | pre-commit-hook | Pre-commit blocks hardcoded values | Hook is local system hook | tests/test_boundary_compliance.py | test_precommit_hook_entry_correct | checker-boundary |
| S44 | pre-commit-hook | Pre-commit blocks hardcoded values | Ruff hooks cover full project | tests/test_precommit_hook_files_pattern | N/A (combined with S30) | checker-boundary |
| S45 | ci-pipeline-split | CI split into parallel jobs | Dedicated lint-and-typecheck job | tests/test_boundary_compliance.py | test_ci_has_gatekeeper_job | checker-boundary |
| S46 | ci-pipeline-split | CI split into parallel jobs | Dedicated unit-tests job | tests/test_boundary_compliance.py | test_ci_gatekeeper_runs_g5_tests | checker-boundary |
| S47 | ci-pipeline-split | CI split into parallel jobs | Dedicated integration-tests job | tests/test_boundary_compliance.py | test_ci_gatekeeper_runs_checker_script | checker-boundary |
| S48 | ci-pipeline-split | CI split into parallel jobs | Dedicated gatekeeper job | tests/test_boundary_compliance.py | test_ci_has_gatekeeper_job | checker-boundary |
| S49 | ci-pipeline-split | CI split into parallel jobs | Jobs use same timeout/markers | tests/test_boundary_compliance.py | test_ci_gatekeeper_runs_g5_tests | checker-boundary |
| S50 | test-database-service | Docker test DB service | Available on port 5433 | tests/test_docker_test_db.py | test_test_database_service_configured_in_compose | docker-test-db |
| S51 | test-database-service | Docker test DB service | Uses test-safe credentials | tests/test_docker_test_db.py | test_test_database_uses_test_safe_credentials | docker-test-db |
| S52 | test-database-service | Docker test DB service | Does not conflict with production | tests/test_docker_test_db.py | test_test_database_port_differs_from_production | docker-test-db |
| S53 | test-database-service | Docker test DB service | Integration tests can connect | tests/test_docker_test_db.py | test_docker_compose_parses_cleanly | docker-test-db |

## Delegation Groups

### Group: checker-core

**Scope:** tests/test_hardcode_checker_core.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_hardcode_checker_core.py | 10 | NEW |

### Group: checker-urls

**Scope:** tests/test_hardcode_checker_production_urls.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_hardcode_checker_production_urls.py | 6 | NEW |

### Group: checker-regression

**Scope:** tests/test_hardcode_checker_regression.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_hardcode_checker_regression.py | 8 | NEW |

### Group: checker-boundary

**Scope:** tests/test_boundary_compliance.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_boundary_compliance.py | 10 | NEW |

### Group: checker-cache-expand

**Scope:** tests/test_conftest_checker_cache.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_conftest_checker_cache.py | 7 (+8 new, 12 total) | EXPAND |

### Group: docker-test-db

**Scope:** tests/test_docker_test_db.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_docker_test_db.py | 4 | NEW |

### Group: pre-commit-ci-config

**Scope:** .pre-commit-config.yaml, .github/workflows/quality.yml

| File | Scenarios | Action |
|---|---|---|
| .pre-commit-config.yaml | N/A | NEW |
| .github/workflows/quality.yml | N/A | REWRITE |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| tests/test_conftest_checker_cache.py | Add 8 tests (hash coverage, performance budgets, all-mode subprocess comparison) | Requirement: Cache fixture meta-tests — Scenarios S35-S41 |
| scripts/check-test-hardcodes.sh | Add 4 gatekeeper test files to EXCLUDE_FILES | Design D3: self-exclusion for synthetic test files |
| docker-compose.yml | Add test-database service (PostgreSQL 18, port 5433) | Requirement: test-database-service — Scenarios S50-S53 |

## Risks & Edge Cases

| # | Risk | Coverage Check | Group |
|---|---|---|---|
| R1 | Pre-commit hook produces false positives on first run | `test_boundary_mode_passes_on_clean_codebase` (S25) verifies checker exit 0; `test_precommit_hook_exists` (S28/S42) verifies hook config | checker-boundary |
| R2 | Synthetic test files not cleaned up, polluting scan directories | `test_cleanup_stale_temp_files_removes_leftovers` (existing S15) verifies cleanup; synthetic tests use `_gate_synth_` prefix to avoid cleanup | checker-core |
| R3 | Performance budget tests flake on slow CI runners | `test_hash_within_subsecond_budget` (S39) uses generous 1.0s budget; `test_cache_startup_within_budget` (S40) uses 10.0s — validated by copium across CI and local | checker-cache-expand |
| R4 | CI gatekeeper job fails because checker script not executable | Script already committed with `chmod +x` from Phase 3; CI checkout preserves permissions | pre-commit-ci-config |
| R5 | CI ruff/black adding tests/ reveals pre-existing lint issues | Run `make lint` before final commit to baseline; add to EXCLUDE_FILES or fix as needed | pre-commit-ci-config |
| R6 | Docker test-database port 5433 conflicts with host PostgreSQL | `test_test_database_port_differs_from_production` (S52) verifies port 5433 ≠ 5432 | docker-test-db |
| R7 | test_boundary_compliance.py parametrized tests multiply runtime | llmGateway has ~15 boundary files (vs copium's 31); estimated ~30s runtime | checker-boundary |
