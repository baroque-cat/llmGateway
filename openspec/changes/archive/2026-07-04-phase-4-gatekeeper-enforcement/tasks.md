## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `test-ref`
- [x] 1.2 Run `make test` to verify the full test suite passes before making changes
- [x] 1.3 Run `make lint && make typecheck` to verify no pre-existing lint/type issues

## 2. EXCLUDE_FILES Update (dependency for synthetic tests)

- [x] 2.1 Add `test_hardcode_checker_core.py` to EXCLUDE_FILES in `scripts/check-test-hardcodes.sh`
- [x] 2.2 Add `test_hardcode_checker_production_urls.py` to EXCLUDE_FILES
- [x] 2.3 Add `test_boundary_compliance.py` to EXCLUDE_FILES
- [x] 2.4 Add `test_hardcode_checker_regression.py` to EXCLUDE_FILES
- [x] 2.5 Run `bash scripts/check-test-hardcodes.sh all` — must exit 0

## 3. Pre-commit Hook

- [x] 3.1 Create `.pre-commit-config.yaml` with ruff and ruff-format hooks (rev: v0.11.0, files: `^(src|tests|main\.py)/`)
- [x] 3.2 Add `ban-test-hardcodes` local hook: `entry: bash scripts/check-test-hardcodes.sh`, `files: ^tests/`, `pass_filenames: false`
- [x] 3.3 Verify hook works: `pre-commit run ban-test-hardcodes --all-files` — must pass

## 4. Docker Compose Test Database

- [x] 4.1 Add `test-database` service to `docker-compose.yml`: image `postgres:18-alpine`, port `5433:5432`, env: POSTGRES_USER=test_user, POSTGRES_PASSWORD=test_password, POSTGRES_DB=test_db
- [x] 4.2 Verify service starts: `docker compose up -d test-database && docker compose ps` — must show healthy
- [x] 4.3 Verify port isolation: production `database` on 5432 and `test-database` on 5433 do not conflict
- [x] 4.4 Run `make test-postgres` if postgres tests exist, or verify connection manually

## 5. CI Pipeline Split

- [x] 5.1 Rewrite `.github/workflows/quality.yml` — replace single `check` job with 4 parallel jobs
- [x] 5.2 Job `lint-and-typecheck`: pyright `src/ main.py` + ruff check `src/ tests/ main.py` + black --check `src/ tests/ main.py`
- [x] 5.3 Job `unit-tests`: G1 (`tests/unit/ --ignore=tests/unit/config`) without `-` prefix + G2 (`tests/unit/config/`) with `|| true`
- [x] 5.4 Job `integration-tests`: G3 (`tests/integration/ tests/security/ tests/e2e/`) + G4 (`tests/batching/`) with `|| true`
- [x] 5.5 Job `gatekeeper`: `bash scripts/check-test-hardcodes.sh all` + G5 inversion pytest with `|| true`
- [x] 5.6 Add `--timeout=30` and `-m "not slow and not postgres"` to all test jobs
- [x] 5.7 Add coverage step to `unit-tests` job with `if: github.event_name == 'push'`

## 6. Tier 2 Synthetic Tests Implementation

### 6A. Checker Core Tests

- [x] 6A.1 Review copium's `test_hardcode_checker_core.py` at `/home/openuser/bots/copium/tgcopiumapp/tests/test_hardcode_checker_core.py` — understand `_make_temp_py()` helper and `_run_checker()` pattern
- [x] 6A.2 Adapt `_make_temp_py()` helper — uses `tempfile.NamedTemporaryFile` with `prefix="_gate_synth_"`, `suffix=".py"`, `delete=False`, placed in target scan directory
- [x] 6A.3 Adapt `_run_checker()` helper — `subprocess.run(["bash", str(CHECK_SCRIPT), mode])` with `capture_output=True, text=True, timeout=30`
- [x] 6A.4 Implement `test_canonical_detects_banned_production_url` (S1) — place temp file with production URL in `tests/unit/`, run canonical mode, assert non-zero rc + `CANONICAL VIOLATION`
- [x] 6A.5 Implement `test_canonical_detects_banned_secret` (S2) — same for secret pattern
- [x] 6A.6 Implement `test_canonical_detects_banned_db_param` (S3) — same for DB param
- [x] 6A.7 Implement `test_canonical_detects_banned_model` (S4) — same for model name
- [x] 6A.8 Implement `test_canonical_detects_banned_provider_type` (S5) — same for provider type regex
- [x] 6A.9 Implement `test_boundary_allows_with_annotation` (S6) — temp file with `# boundary:` annotation in `tests/integration/`, boundary mode, assert exit 0
- [x] 6A.10 Implement `test_boundary_rejects_without_annotation` (S7) — temp file without annotation, boundary mode, assert non-zero rc
- [x] 6A.11 Implement `test_production_url_always_banned_boundary` (S8) — production URL with `# boundary:` in integration dir, boundary mode, still violation
- [x] 6A.12 Implement `test_root_detects_banned_model` (S9) — temp file at `tests/` root, root mode, assert `ROOT VIOLATION`
- [x] 6A.13 Implement `test_all_mode_composition` (S10) — temp files in multiple dirs, all mode, assert violations from all modes

### 6B. Production URLs Tests

- [x] 6B.1 Review copium's `test_hardcode_checker_production_urls.py` — understand parametrized URL detection pattern
- [x] 6B.2 Implement `_make_temp_py()` helper with same pattern as core tests
- [x] 6B.3 Implement `test_canonical_detects_production_url` (S11)
- [x] 6B.4 Implement `test_boundary_detects_production_url` (S12)
- [x] 6B.5 Implement `test_boundary_rejects_url_even_with_annotation` (S13) — URL + `# boundary:` still banned
- [x] 6B.6 Implement `test_root_detects_production_url` (S14)
- [x] 6B.7 Implement `test_all_mode_detects_url_in_canonical_dir` (S15)
- [x] 6B.8 Implement `test_all_urls_in_banned_list_detected` (S16) — parametrized over all 6 production URLs

### 6C. Regression Tests

- [x] 6C.1 Review copium's `test_hardcode_checker_regression.py` — understand `_normalize_output()` helper
- [x] 6C.2 Implement `_normalize_output()` — strips timing-dependent lines for deterministic comparison
- [x] 6C.3 Implement `test_all_mode_passes_on_clean_codebase` (S17) — use `checker_result("all")` cache fixture
- [x] 6C.4 Implement `test_canonical_mode_passes` (S18)
- [x] 6C.5 Implement `test_boundary_mode_passes` (S19)
- [x] 6C.6 Implement `test_root_mode_passes` (S20)
- [x] 6C.7 Implement `test_no_args_equals_all_mode` (S22) — direct `subprocess.run` comparison
- [x] 6C.8 Implement `test_output_consistent_across_runs` (S21) — two runs → normalized output identical
- [x] 6C.9 Implement `test_summary_line_present_on_success` (S23)
- [x] 6C.10 Implement `test_exclude_files_covers_all_gatekeeper_tests` (S24) — parse EXCLUDE_FILES array from script

### 6D. Boundary Compliance Tests

- [x] 6D.1 Review copium's `test_boundary_compliance.py` — understand pre-commit/CI config parsing via `yaml.safe_load`
- [x] 6D.2 Implement `test_boundary_mode_passes_on_clean_codebase` (S25) — use `checker_result("boundary")` fixture
- [x] 6D.3 Implement `test_boundary_files_have_annotations` (S26) — parametrized over boundary test files in `tests/integration/`, `tests/security/`, `tests/e2e/`
- [x] 6D.4 Implement `test_removing_annotation_triggers_violation` (S27) — corrupt a boundary file by removing `# boundary:`, verify detection
- [x] 6D.5 Implement `test_precommit_hook_exists` (S28/S42) — parse `.pre-commit-config.yaml`, verify `ban-test-hardcodes` under `local` repo
- [x] 6D.6 Implement `test_precommit_hook_entry_correct` (S29/S43) — verify `entry` and `files` fields
- [x] 6D.7 Implement `test_precommit_hook_pass_filenames_false` (S31) — verify `pass_filenames: false`
- [x] 6D.8 Implement `test_ci_has_gatekeeper_job` (S32/S45/S48) — parse `.github/workflows/quality.yml`, verify `gatekeeper` job
- [x] 6D.9 Implement `test_ci_gatekeeper_runs_checker_script` (S33/S47) — verify gatekeeper job step
- [x] 6D.10 Implement `test_ci_gatekeeper_runs_g5_tests` (S34/S46/S49) — verify G5 pytest command in gatekeeper job

### 6E. Cache Fixture Expansion

- [x] 6E.1 Review copium's `test_conftest_checker_cache.py` — understand hash and performance test patterns
- [x] 6E.2 Implement `test_hash_covers_script_content` (S35) — modify checker script, verify hash changes
- [x] 6E.3 Implement `test_hash_covers_scanned_test_files` (S36) — add .py file to scan dir, verify hash changes, cleanup
- [x] 6E.4 Implement `test_hash_excludes_pycache` (S37) — add file to `__pycache__/`, verify hash unchanged
- [x] 6E.5 Implement `test_hash_deterministic` (S38) — two calls, same hash
- [x] 6E.6 Implement `test_hash_within_subsecond_budget` (S39) — `time.perf_counter()`, assert < 1.0s
- [x] 6E.7 Implement `test_cache_startup_within_budget` (S40) — `time.perf_counter()`, assert < 10.0s
- [x] 6E.8 Implement `test_checker_result_all_matches_direct_subprocess` (S41) — composed result == fresh `subprocess.run` call

## 7. Docker Test DB Tests

- [x] 7.1 Create `tests/test_docker_test_db.py` — validates docker-compose.yml test-database service
- [x] 7.2 Implement `test_test_database_service_configured_in_compose` (S50) — parse `docker-compose.yml`, verify `test-database` service with `postgres:18-alpine` image
- [x] 7.3 Implement `test_test_database_uses_test_safe_credentials` (S51) — verify POSTGRES_USER=test_user, etc.
- [x] 7.4 Implement `test_test_database_port_differs_from_production` (S52) — verify port 5433 ≠ 5432
- [x] 7.5 Implement `test_docker_compose_parses_cleanly` (S53) — verify YAML parses without errors

## 8. Integration & Verification

- [x] 8.1 Run `bash scripts/check-test-hardcodes.sh all` — must exit 0 with new EXCLUDE_FILES
- [x] 8.2 Run `make test` — G5 must collect all new test files, all must pass
- [x] 8.3 Run `make lint && make typecheck` — zero errors on new files
- [x] 8.4 Run `pre-commit run ban-test-hardcodes --all-files` — must pass
- [x] 8.5 Run `pre-commit run ruff --all-files` — must pass or fix issues
- [x] 8.6 Verify `docker compose up -d test-database` starts successfully
- [x] 8.7 Verify CI YAML is valid: parse `.github/workflows/quality.yml` with Python yaml
