# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | metrics-fixture-dedup | Metrics collector is isolated between tests via shared autouse fixture | Shared fixture resets collector singleton before and after each test | `tests/unit/metrics/test_metrics_isolation.py` | `test_autouse_fixture_resets_collector_and_deletes_env_vars` | metrics-fixture-dedup |
| 2 | metrics-fixture-dedup | Metrics collector is isolated between tests via shared autouse fixture | Shared fixture covers all metrics unit test files | `tests/test_metrics_fixture_dedup.py` | `test_no_duplicate_isolation_fixtures_in_metrics_unit_tests` | metrics-fixture-dedup |
| 3 | metrics-fixture-dedup | Metrics collector is isolated between tests via shared autouse fixture | Shared fixture covers all metrics unit test files | `tests/test_metrics_fixture_dedup.py` | `test_unit_conftest_re_exports_isolation_fixture` | metrics-fixture-dedup |
| 4 | metrics-fixture-dedup | Metrics collector is isolated between tests via shared autouse fixture | Integration tests have their own isolation fixture | `tests/test_metrics_fixture_dedup.py` | `test_integration_conftest_provides_isolation_fixture` | metrics-fixture-dedup |
| 5 | metrics-fixture-dedup | Metrics collector is isolated between tests via shared autouse fixture | Integration tests have their own isolation fixture | `tests/test_metrics_fixture_dedup.py` | `test_integration_metrics_test_has_no_inline_fixture` | metrics-fixture-dedup |
| 6 | metrics-fixture-dedup | Prometheus backend tests use shared fixture instead of workarounds | Prometheus tests no longer depend on _make_unique_name | `tests/test_metrics_fixture_dedup.py` | `test_prometheus_backend_tests_do_not_use_make_unique_name` | metrics-fixture-dedup |
| 7 | security-gatekeeper-tests | Gatekeeper test verifies no hardcoded secrets in source code | .env is in .gitignore | `tests/test_security.py` | `test_env_in_gitignore` | security-gatekeeper |
| 8 | security-gatekeeper-tests | Gatekeeper test verifies no hardcoded secrets in source code | No hardcoded passwords in source files | `tests/test_security.py` | `test_no_hardcoded_passwords_in_source_files` | security-gatekeeper |
| 9 | security-gatekeeper-tests | Gatekeeper test verifies no hardcoded secrets in source code | No private key files committed | `tests/test_security.py` | `test_no_private_key_files_committed` | security-gatekeeper |
| 10 | security-gatekeeper-tests | Gatekeeper test verifies no hardcoded secrets in source code | No committed .env files except .env.example | `tests/test_security.py` | `test_no_committed_env_files_except_example` | security-gatekeeper |
| 11 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | All 4 required jobs are present | `tests/test_ci_pipeline.py` | `test_all_four_required_jobs_present` | ci-pipeline-gatekeeper |
| 12 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | All jobs run in parallel | `tests/test_ci_pipeline.py` | `test_all_jobs_run_in_parallel_no_needs` | ci-pipeline-gatekeeper |
| 13 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | Lint job includes tests/ in ruff and black scope | `tests/test_ci_pipeline.py` | `test_lint_job_includes_tests_in_ruff_and_black` | ci-pipeline-gatekeeper |
| 14 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | Unit-tests job has coverage and codecov steps | `tests/test_ci_pipeline.py` | `test_unit_tests_job_has_coverage_and_codecov` | ci-pipeline-gatekeeper |
| 15 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | Gatekeeper job runs checker script before G5 tests | `tests/test_ci_pipeline.py` | `test_gatekeeper_job_runs_checker_before_g5_tests` | ci-pipeline-gatekeeper |
| 16 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | All test jobs use correct timeout and markers | `tests/test_ci_pipeline.py` | `test_all_test_jobs_use_correct_timeout_and_markers` | ci-pipeline-gatekeeper |
| 17 | ci-pipeline-gatekeeper-tests | Gatekeeper test validates CI workflow structure in detail | Workflow has required triggers | `tests/test_ci_pipeline.py` | `test_workflow_has_required_push_and_pr_triggers` | ci-pipeline-gatekeeper |
| 18 | ci-pipeline-split | CI workflow runs on a nightly schedule | Nightly CI run at 03:00 UTC | `tests/test_ci_pipeline.py` | `test_nightly_ci_run_at_03_00_utc` | ci-pipeline-gatekeeper |
| 19 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | config/ layer does not import from db/ or services/ | `tests/test_layer_import_scan.py` | `test_config_layer_no_db_or_services_imports` | layer-import-gatekeeper |
| 20 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | db/ layer does not import from providers/ or services/ | `tests/test_layer_import_scan.py` | `test_db_layer_no_providers_or_services_imports` | layer-import-gatekeeper |
| 21 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | metrics/ layer does not import from services/ or providers/ | `tests/test_layer_import_scan.py` | `test_metrics_layer_no_services_or_providers_imports` | layer-import-gatekeeper |
| 22 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | providers/ layer does not import from services/ | `tests/test_layer_import_scan.py` | `test_providers_layer_no_services_imports` | layer-import-gatekeeper |
| 23 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | core/ layer has no forbidden layer dependencies | `tests/test_layer_import_scan.py` | `test_core_layer_no_forbidden_layer_dependencies` | layer-import-gatekeeper |
| 24 | layer-import-gatekeeper-tests | Gatekeeper test enforces architectural layer import boundaries | Well-known exceptions are whitelisted | `tests/test_layer_import_scan.py` | `test_well_known_exceptions_are_whitelisted` | layer-import-gatekeeper |
| 25 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | Trailing whitespace is stripped | `tests/test_pre_commit_config.py` | `test_trailing_whitespace_hook_configured` | pre-commit-config |
| 26 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | Files end with a single newline | `tests/test_pre_commit_config.py` | `test_end_of_file_fixer_hook_configured` | pre-commit-config |
| 27 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | YAML, TOML, and JSON files are syntactically valid | `tests/test_pre_commit_config.py` | `test_check_yaml_toml_json_hooks_configured` | pre-commit-config |
| 28 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | Merge conflict markers are detected | `tests/test_pre_commit_config.py` | `test_check_merge_conflict_hook_configured` | pre-commit-config |
| 29 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | Private keys are not accidentally committed | `tests/test_pre_commit_config.py` | `test_detect_private_key_hook_configured` | pre-commit-config |
| 30 | pre-commit-hook | File hygiene hooks enforce repository cleanliness | Line endings are normalized to LF | `tests/test_pre_commit_config.py` | `test_mixed_line_ending_hook_configured` | pre-commit-config |
| 31 | pre-commit-hook | Type checking runs in pre-commit for src/ | Pyright runs on changed source files | `tests/test_pre_commit_config.py` | `test_pyright_hook_targets_src_and_main_only` | pre-commit-config |
| 32 | pre-commit-hook | Shell scripts are linted with shellcheck | Shellcheck validates gatekeeper script | `tests/test_pre_commit_config.py` | `test_shellcheck_hook_lints_scripts_directory` | pre-commit-config |

## Delegation Groups

### Group: metrics-fixture-dedup

**Scope:** `tests/unit/metrics/test_metrics_isolation.py`, `tests/test_metrics_fixture_dedup.py`, `tests/unit/metrics/conftest.py` (new), `tests/unit/conftest.py` (new), `tests/integration/conftest.py` (modified)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/metrics/test_metrics_isolation.py` | #1 Shared fixture resets collector singleton before and after each test | CREATE — behavioral test that runs under the autouse fixture and asserts `METRICS_BACKEND` / `PROMETHEUS_MULTIPROC_DIR` are deleted from `os.environ` and `get_collector()` returns a fresh singleton; a second test sets state on the collector and a third verifies that state is gone, proving the after-test cleanup ran |
| `tests/test_metrics_fixture_dedup.py` | #2 No duplicate isolation fixtures in metrics unit tests; #3 `tests/unit/conftest.py` re-exports fixture; #4 Integration conftest provides isolation fixture; #5 Integration metrics test has no inline fixture; #6 Prometheus tests do not use `_make_unique_name` | CREATE — structural source-scanning tests that read conftest/test files as text and assert fixture presence/absence |

### Group: security-gatekeeper

**Scope:** `tests/test_security.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_security.py` | #7 .env in .gitignore; #8 No hardcoded passwords in source; #9 No private key files committed; #10 No committed .env files except .env.example | CREATE — root-level gatekeeper test scanning repo files for secrets, key files, and .env leakage; uses `Path.rglob()` and regex patterns; respects `EXCLUDE_FILES` from gatekeeper script for password scan |

### Group: ci-pipeline-gatekeeper

**Scope:** `tests/test_ci_pipeline.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_ci_pipeline.py` | #11 All 4 required jobs present; #12 All jobs run in parallel; #13 Lint job includes tests/ in ruff and black; #14 Unit-tests job has coverage and codecov; #15 Gatekeeper job runs checker before G5; #16 All test jobs use correct timeout and markers; #17 Workflow has required push and PR triggers; #18 Nightly CI run at 03:00 UTC | CREATE — root-level gatekeeper test parsing `.github/workflows/quality.yml` with `yaml.safe_load()` and asserting job names, step commands, `needs` absence, `runs-on`, timeout/marker flags, trigger configuration, and cron schedule |

### Group: layer-import-gatekeeper

**Scope:** `tests/test_layer_import_scan.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_layer_import_scan.py` | #19 config/ no db or services imports; #20 db/ no providers or services imports; #21 metrics/ no services or providers imports; #22 providers/ no services imports; #23 core/ no forbidden layer dependencies; #24 Well-known exceptions are whitelisted | CREATE — root-level gatekeeper test using `ast.parse()` on every `.py` file under each `src/` subdirectory; extracts `Import` and `ImportFrom` nodes; checks module paths against forbidden-layer sets; validates whitelist mechanism suppresses approved exceptions |

### Group: pre-commit-config

**Scope:** `tests/test_pre_commit_config.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_pre_commit_config.py` | #25 trailing-whitespace; #26 end-of-file-fixer; #27 check-yaml/check-toml/check-json; #28 check-merge-conflict; #29 detect-private-key; #30 mixed-line-ending; #31 pyright on src/ and main.py; #32 shellcheck on scripts/ | CREATE — root-level gatekeeper test parsing `.pre-commit-config.yaml` with `yaml.safe_load()` and asserting each hook ID is present with correct `files`/`args`/`pass_filenames` configuration |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/unit/metrics/test_metrics_factory.py` | Remove the `_clean_env_and_singleton` autouse fixture (lines 23–31) and the `import os` if no longer needed | Replaced by shared `_isolate_metrics_collector` autouse fixture from `tests/unit/metrics/conftest.py`; `os.environ.pop()` calls are superseded by `monkeypatch.delenv()` |
| `tests/unit/metrics/test_memory_backend.py` | Remove the `_isolate_collector_for_memory_backend` autouse fixture (lines 136–145) and the `import os` if no longer needed | Replaced by shared `_isolate_metrics_collector` autouse fixture from `tests/unit/metrics/conftest.py` |
| `tests/unit/services/test_keeper_metrics.py` | Remove the `_isolate_collector` autouse fixture (lines 34–41) and the `import os` if no longer needed | Replaced by shared `_isolate_metrics_collector` re-exported from `tests/unit/conftest.py` (covers `tests/unit/services/` subdirectory) |
| `tests/integration/test_keeper_metrics_endpoint.py` | Remove the `_isolate_collector` autouse fixture (lines 49–55) and the `import os` if no longer needed | Replaced by parallel `_isolate_metrics_collector` fixture added to `tests/integration/conftest.py` (conftest hierarchy does not cross unit/integration boundary) |
| `tests/unit/metrics/test_prometheus_backend.py` | Remove the `_make_unique_name()` counter function (lines 33–37); replace all `_make_unique_name("...")` calls with static metric names for non-REGISTRY tests; keep unique-name logic only for tests that intentionally exercise `REGISTRY` collision scenarios | Shared `_isolate_metrics_collector` fixture resets the collector singleton between tests, preventing Prometheus duplicate-registration errors for the majority of tests; only REGISTRY-level collision tests need unique names |
| `tests/integration/conftest.py` | Add `_isolate_metrics_collector` autouse fixture using `reset_collector()` + `monkeypatch.delenv("METRICS_BACKEND", raising=False)` + `monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)` before and after `yield` | Integration tests need their own parallel fixture because `tests/unit/metrics/conftest.py` only covers the `tests/unit/` subtree; the conftest hierarchy does not cross the unit/integration directory boundary |
| `.pre-commit-config.yaml` | Add `pre-commit/pre-commit-hooks` repo with 8 hooks (trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-json, check-merge-conflict, detect-private-key, mixed-line-ending); add `pyright` local hook with `entry: poetry run pyright src/ main.py`, `pass_filenames: false`, `files: ^src/|^main\.py$`; add `shellcheck` hook from `https://github.com/koalaman/shellcheck-precommit` scoped to `scripts/` | Spec requires file hygiene, type checking in pre-commit for `src/` only (not `tests/` per D3 decision), and shell linting for `scripts/` directory |
| `.github/workflows/quality.yml` | Add `schedule:` trigger with `cron: '0 3 * * *'` to the `on:` section | Spec requires nightly CI run at 03:00 UTC to catch regressions from dependency updates |
| `scripts/check-test-hardcodes.sh` | Add new gatekeeper test files to the `EXCLUDE_FILES` array: `test_security.py`, `test_ci_pipeline.py`, `test_layer_import_scan.py`, `test_pre_commit_config.py`, `test_metrics_fixture_dedup.py` | These new test files contain banned patterns (password-like strings, model names, URLs) as test data for assertion construction; self-exclusion prevents the gatekeeper script from flagging them |

## Risks & Edge Cases

- **Shared fixture breaks tests that relied on specific `os.environ` state** The new `monkeypatch.delenv()` approach is more predictable than `os.environ.pop()`, but tests that implicitly depended on env var leakage between tests could break. → Covered by `test_autouse_fixture_resets_collector_and_deletes_env_vars` in `tests/unit/metrics/test_metrics_isolation.py` which verifies the fixture deletes `METRICS_BACKEND` and `PROMETHEUS_MULTIPROC_DIR` and resets the collector singleton before the test runs; a companion test sets state and a follow-up test verifies it is gone, proving the after-test cleanup.

- **`check-yaml` pre-commit hook fails on existing YAML files** All existing YAML files (`docker-compose.yml`, `quality.yml`, `.pre-commit-config.yaml`, `config/*.yaml`) should parse cleanly, but edge cases like templated YAML with `${ENV_VAR}` placeholders could cause issues. → Covered by `test_check_yaml_toml_json_hooks_configured` in `tests/test_pre_commit_config.py` which verifies the hook is configured; a one-time `pre-commit run --all-files` pass validates all existing files parse correctly.

- **`shellcheck` produces false positives on the gatekeeper script** The 472-line `check-test-hardcodes.sh` uses arrays, functions, and `set -euo pipefail`. Shellcheck may flag patterns that are intentional (e.g., word splitting in `EXCLUDE_FILES` array expansion). → Covered by `test_shellcheck_hook_lints_scripts_directory` in `tests/test_pre_commit_config.py` which verifies the hook is configured and scoped to `scripts/`; manual review of shellcheck output is needed on first run to add `# shellcheck disable` directives if necessary.

- **`trailing-whitespace` / `end-of-file-fixer` produce large diffs on first run** Running these hooks on all existing files for the first time may auto-fix many files, creating a noisy commit that obscures the actual configuration change. → Covered by `test_trailing_whitespace_hook_configured` and `test_end_of_file_fixer_hook_configured` in `tests/test_pre_commit_config.py` which verify the hooks are present; mitigation is to run `pre-commit run --all-files` once and commit the auto-fixes in a separate commit before enabling the hooks.

- **Pyright in pre-commit slows down commits** Pyright on `src/` adds latency to every commit touching source files, potentially discouraging frequent commits. → Covered by `test_pyright_hook_targets_src_and_main_only` in `tests/test_pre_commit_config.py` which verifies the hook is scoped to `src/` and `main.py` only (not `tests/` per D3 decision), uses `pass_filenames: false` for full project context, and only triggers when files under `src/` or `main.py` change.

- **`test_layer_import_scan.py` has false positives for legitimate imports** Some cross-layer imports may be architecturally valid (e.g., `src/core/batching/` importing from `src/core/`, or `src/providers/impl/` importing from `src/providers/base.py`). The AST scan could flag these as violations. → Covered by `test_well_known_exceptions_are_whitelisted` in `tests/test_layer_import_scan.py` which verifies the whitelist mechanism suppresses approved exceptions with documented comments; also covered by `test_core_layer_no_forbidden_layer_dependencies` which verifies that `src.core` self-references are permitted while cross-layer imports are flagged.

- **`test_security.py` finds pre-existing issues** Scanning `src/` for secret-like patterns may find strings that look like secrets but are benign (e.g., placeholder text in docstrings, example tokens in configuration templates). → Covered by `test_no_hardcoded_passwords_in_source_files` in `tests/test_security.py` which respects `EXCLUDE_FILES` from the gatekeeper script and uses precise regex patterns (e.g., `password="test_secret"`) rather than broad substring matches; `test_no_private_key_files_committed` checks file extensions and names only, not file contents.
