# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| S1 | canonical-config | CanonicalConfig provides a single source of truth for test configuration | CanonicalConfig parses example files correctly | tests/test_canonical_config.py | test_parses_example_files_correctly | canonical-config |
| S2 | canonical-config | CanonicalConfig provides a single source of truth for test configuration | CanonicalConfig replaces setdefault in conftest.py | tests/test_canonical_fixtures.py | test_canonical_config_replaces_setdefault | canonical-config |
| S3 | canonical-config | CanonicalConfig provides a single source of truth for test configuration | Duplicated _BASE_ENV dicts are replaced | tests/test_canonical_integrity.py | test_no_duplicated_base_env_dicts | gatekeeper-structural-tests |
| S4 | canonical-config | CanonicalConfig provides a single source of truth for test configuration | CanonicalConfig is import-safe from any test file | tests/test_canonical_config.py | test_import_safe_from_any_test_file | canonical-config |
| S5 | canonical-config | Shared test constants are centralized | Mock tokens are accessible from _constants | tests/test_constants.py | test_mock_tokens_accessible_from_constants | canonical-config |
| S6 | canonical-config | Shared test constants are centralized | _constants replaces duplicated mock values | tests/test_constants.py | test_constants_replaces_duplicated_mock_values | canonical-config |
| S7 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | Canonical mode enforces strict zero-hardcodes in unit tests | tests/test_hardcode_checker_modes.py | test_canonical_mode_enforces_strict_zero_hardcodes | gatekeeper-checker-modes |
| S8 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | Boundary mode implements whitelist via # boundary: annotations | tests/test_hardcode_checker_modes.py | test_boundary_mode_whitelist_via_annotations | gatekeeper-checker-modes |
| S9 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | Root mode enforces strict checks on root-level test files | tests/test_hardcode_checker_modes.py | test_root_mode_enforces_strict_checks | gatekeeper-checker-modes |
| S10 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | All mode runs canonical, boundary, and root sequentially | tests/test_hardcode_checker_modes.py | test_all_mode_runs_all_three_sequentially | gatekeeper-checker-modes |
| S11 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | Banned-pattern arrays catch all prohibited values | tests/test_hardcode_checker_patterns.py | test_banned_pattern_arrays_catch_prohibited_values | gatekeeper-checker-modes |
| S12 | gatekeeper-hardcode-checker | Gatekeeper script detects hardcoded test values | Infrastructure files are excluded from scanning | tests/test_hardcode_checker_patterns.py | test_infrastructure_files_excluded_from_scanning | gatekeeper-checker-modes |
| S13 | gatekeeper-hardcode-checker | Cache fixtures prevent repeated checker script execution | _cached_checker_results runs the script once per mode | tests/test_checker_cache_fixtures.py | test_cached_checker_results_runs_once_per_mode | gatekeeper-cache-fixtures |
| S14 | gatekeeper-hardcode-checker | Cache fixtures prevent repeated checker script execution | checker_result provides access to cached results | tests/test_checker_cache_fixtures.py | test_checker_result_provides_cached_access | gatekeeper-cache-fixtures |
| S15 | gatekeeper-hardcode-checker | Cache fixtures prevent repeated checker script execution | _cleanup_stale_temp_files removes leftovers from crashed sessions | tests/test_checker_cache_fixtures.py | test_cleanup_stale_temp_files_removes_leftovers | gatekeeper-cache-fixtures |
| S16 | gatekeeper-hardcode-checker | Cache fixtures prevent repeated checker script execution | _compute_checker_hash reflects file changes | tests/test_checker_cache_fixtures.py | test_compute_checker_hash_reflects_file_changes | gatekeeper-cache-fixtures |
| S17 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_project_structure validates directory layout | tests/test_project_structure.py | test_project_structure_validates_directory_layout | gatekeeper-structural-tests |
| S18 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_makefile_groups validates Makefile structure | tests/test_makefile_groups.py | test_makefile_groups_validates_structure | gatekeeper-structural-tests |
| S19 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_canonical_integrity verifies CanonicalConfig completeness | tests/test_canonical_integrity.py | test_canonical_integrity_verifies_completeness | gatekeeper-structural-tests |
| S20 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_secret_isolation prevents secret leakage | tests/test_secret_isolation.py | test_secret_isolation_prevents_leakage | gatekeeper-structural-tests |
| S21 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_env_example validates .env.example completeness | tests/test_env_example.py | test_env_example_validates_completeness | gatekeeper-structural-tests |
| S22 | gatekeeper-hardcode-checker | Structural gatekeeper tests enforce project integrity | test_documentation_sync verifies TESTING docs | tests/test_documentation_sync.py | test_documentation_sync_verifies_testing_docs | gatekeeper-structural-tests |
| S23 | gatekeeper-hardcode-checker | TESTING documentation covers all test infrastructure | TESTING.md serves as the documentation index | tests/test_testing_docs.py | test_testing_md_serves_as_documentation_index | testing-documentation |
| S24 | gatekeeper-hardcode-checker | TESTING documentation covers all test infrastructure | TESTING-GUIDE documents the golden rule of zero hardcodes | tests/test_testing_docs.py | test_testing_guide_documents_golden_rule | testing-documentation |
| S25 | gatekeeper-hardcode-checker | TESTING documentation covers all test infrastructure | TESTING-RUN documents Makefile targets and isolation groups | tests/test_testing_docs.py | test_testing_run_documents_makefile_targets | testing-documentation |
| S26 | gatekeeper-hardcode-checker | TESTING documentation covers all test infrastructure | TESTING-GATEKEEPER documents the gatekeeper infrastructure | tests/test_testing_docs.py | test_testing_gatekeeper_documents_infrastructure | testing-documentation |

## Delegation Groups

### Group: canonical-config

**Scope:** tests/test_canonical_config.py, tests/test_canonical_fixtures.py, tests/test_constants.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_canonical_config.py | 2 | NEW |
| tests/test_canonical_fixtures.py | 1 | NEW |
| tests/test_constants.py | 2 | NEW |

### Group: gatekeeper-checker-modes

**Scope:** tests/test_hardcode_checker_modes.py, tests/test_hardcode_checker_patterns.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_hardcode_checker_modes.py | 4 | NEW |
| tests/test_hardcode_checker_patterns.py | 2 | NEW |

### Group: gatekeeper-cache-fixtures

**Scope:** tests/test_checker_cache_fixtures.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_checker_cache_fixtures.py | 4 | NEW |

### Group: gatekeeper-structural-tests

**Scope:** tests/test_project_structure.py, tests/test_makefile_groups.py, tests/test_canonical_integrity.py, tests/test_secret_isolation.py, tests/test_env_example.py, tests/test_documentation_sync.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_project_structure.py | 1 | NEW |
| tests/test_makefile_groups.py | 1 | NEW |
| tests/test_canonical_integrity.py | 2 | NEW |
| tests/test_secret_isolation.py | 1 | NEW |
| tests/test_env_example.py | 1 | NEW |
| tests/test_documentation_sync.py | 1 | NEW |

### Group: testing-documentation

**Scope:** tests/test_testing_docs.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/test_testing_docs.py | 4 | NEW |

## Test Modifications

| Artifact | Change Type | Reason (spec / design reference) |
|---|---|---|
| tests/_canonical.py | Created | CanonicalConfig frozen dataclass (~50 fields) parsing `.env.example` + `config/example_full_config.yaml` — spec S1/S4, design D1 |
| tests/_constants.py | Created | Shared mock token constants (GEMINI, DEEPSEEK, ANTHROPIC, QWEN, DEFAULT, METRICS) — spec S5/S6 |
| scripts/check-test-hardcodes.sh | Created | 4-mode gatekeeper script (canonical/boundary/root/all) with 7 banned-pattern arrays, boundary whitelist, EXCLUDE_FILES — spec S7-S12, design D2/D4 |
| TESTING.md | Created | Documentation index linking to GUIDE/RUN/GATEKEEPER — spec S23 |
| TESTING-GUIDE.md | Created | Golden Rule, `# boundary:` mechanism, anti-patterns — spec S24 |
| TESTING-RUN.md | Created | Makefile targets, 6 isolation groups G1-G6, timing estimates — spec S25 |
| TESTING-GATEKEEPER.md | Created | 4-mode script architecture, cache fixture chain, 3-tier test classification — spec S26 |
| tests/conftest.py | Modified | Replace `_setup_default_env_vars()` setdefault with `canonical_config` session fixture + `_set_config_vars_from_canonical` autouse fixture (monkeypatch.setenv); add `CheckerResult` namedtuple, `_cached_checker_results`, `checker_result`, `_cleanup_stale_temp_files`, `_compute_checker_hash` — spec S2/S13-S16, design D6/D3 |
| tests/AGENTS.md | Modified | Update directory tree, markers, and CanonicalConfig section — design Goals |
| tests/unit/config/test_config_init.py | Modified | Replace copy-pasted `_BASE_ENV` dict with `CanonicalConfig.from_example_files()` — spec S3, design D6 |
| tests/unit/config/test_gateway_config.py | Modified | Replace copy-pasted `_BASE_ENV` dict with `CanonicalConfig.from_example_files()` — spec S3, design D6 |
| tests/unit/config/test_loader.py | Modified | Replace copy-pasted `_BASE_ENV` dict with `CanonicalConfig.from_example_files()` — spec S3, design D6 |
| tests/unit/config/test_resolve_env_vars.py | Modified | Replace `FULL_ENV` dict (17 vars) with `CanonicalConfig.from_example_files()` reference — spec S3, design D6 |
| pyproject.toml | Modified | Add `ruamel.yaml` to dev dependencies — design Risks (ruamel.yaml not in project dependencies) |

## Risks & Edge Cases

| # | Risk | Coverage Check | Group |
|---|---|---|---|
| R1 | `CanonicalConfig.from_example_files()` fails to parse YAML with `${VAR}` and `${VAR:-default}` placeholders correctly | `test_parses_example_files_correctly` (S1) verifies all ~50 fields match expected values from `.env.example` and `config/example_full_config.yaml`; `_ENV_VAR_RE` regex adapted from copium's verified implementation | canonical-config |
| R2 | Replacing `setdefault` with `monkeypatch.setenv` breaks existing tests | `test_canonical_config_replaces_setdefault` (S2) verifies autouse fixture sets all 17 env vars before every test; full test suite re-run after migration validates no regressions (tests needing different values already use `monkeypatch.setenv` or `patch.dict` which override the autouse fixture) | canonical-config |
| R3 | Gatekeeper script produces false positives on clean codebase | `test_canonical_mode_enforces_strict_zero_hardcodes` (S7), `test_boundary_mode_whitelist_via_annotations` (S8), `test_root_mode_enforces_strict_checks` (S9), `test_all_mode_runs_all_three_sequentially` (S10) run all 4 modes against the clean codebase and assert returncode 0; `test_infrastructure_files_excluded_from_scanning` (S12) verifies EXCLUDE_FILES contains conftest.py, _canonical.py, _constants.py, and all gatekeeper test files | gatekeeper-checker-modes |
| R4 | `_cached_checker_results` fails because checker script doesn't exist yet | Script is created earlier in the same phase; `test_cached_checker_results_runs_once_per_mode` (S13) verifies fixture invokes `check-test-hardcodes.sh` once per mode and raises `FileNotFoundError` with clear message if script is missing | gatekeeper-cache-fixtures |
| R5 | G5 collects 0 tests before gatekeeper tests are written | `test_makefile_groups_validates_structure` (S18) verifies G5 has `-` prefix (fault-tolerant — pytest exit code 5 swallowed by Make) and G1 has no `-` prefix (gate) | gatekeeper-structural-tests |
| R6 | `ruamel.yaml` not in project dependencies | `test_import_safe_from_any_test_file` (S4) verifies `from tests._canonical import CanonicalConfig` succeeds (transitively imports ruamel.yaml); pyproject.toml modification adds `ruamel.yaml` to dev group | canonical-config |
| R7 | Boundary annotation lookback misses annotations across large comment blocks | `test_boundary_mode_whitelist_via_annotations` (S8) verifies 20 non-blank-line lookback catches `# boundary:` annotations (case-insensitive) and that production URLs (`BANNED_URLS`) are always banned even with annotations | gatekeeper-checker-modes |
| R8 | Gatekeeper script is bash — not portable to Windows | `test_all_mode_runs_all_three_sequentially` (S10) verifies script executes and returns expected returncodes on Linux/WSL; Windows developers already use WSL or Docker per Phase 2 design — no dedicated cross-platform test needed | gatekeeper-checker-modes |
