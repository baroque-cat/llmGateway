## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `test-ref`
- [x] 1.2 Run `make test` to verify the full test suite passes before making changes
- [x] 1.3 Add `ruamel.yaml` to dev dependencies: `poetry add --group dev ruamel.yaml`

## 2. CanonicalConfig Infrastructure

- [x] 2.1 Create `tests/_constants.py` with 6 shared mock token constants: MOCK_GEMINI_TOKEN, MOCK_DEEPSEEK_TOKEN, MOCK_ANTHROPIC_TOKEN, MOCK_QWEN_TOKEN, MOCK_DEFAULT_TOKEN, MOCK_METRICS_TOKEN
- [x] 2.2 Create `tests/_canonical.py` with `CanonicalConfig` frozen dataclass (~50 fields): database (5 fields), gateway (3), keeper (1), http_client (4), timeouts (5), metrics (3), provider tokens (5), adaptive batching (6), health policy (4), canonical lists (2). Implement `from_example_files()` classmethod.
- [x] 2.3 Implement `_load_env_example()` in `_canonical.py` — parse `.env.example`, skip comments/blanks, return `dict[str,str]`
- [x] 2.4 Implement `_load_config_example()` in `_canonical.py` — parse `config/example_full_config.yaml` via `ruamel.yaml`, resolve `${VAR}` and `${VAR:-default}` placeholders
- [x] 2.5 Run `poetry run pyright` on `tests/_canonical.py` and `tests/_constants.py` to verify type safety

## 3. conftest.py — CanonicalConfig Fixtures

- [x] 3.1 Add `canonical_config` session-scoped fixture to `tests/conftest.py` — returns `CanonicalConfig.from_example_files()` once per session
- [x] 3.2 Add `_set_config_vars_from_canonical` autouse fixture — calls `monkeypatch.setenv` for all 17 env vars before every test
- [x] 3.3 Remove `_setup_default_env_vars()` function and its module-level call from `tests/conftest.py`
- [x] 3.4 Run `make test` to verify all existing tests pass after setdefault → CanonicalConfig migration
- [x] 3.5 If `make test` reveals migration breakage, fix tests and re-run until all pass

## 4. conftest.py — Gatekeeper Fixtures

- [x] 4.1 Add `CheckerResult` namedtuple to `tests/conftest.py` — fields: `returncode`, `stdout`, `stderr`
- [x] 4.2 Add `_CHECKER_SCRIPT`, `_REPO_ROOT`, `_CHECKER_SCAN_DIRS` module-level constants
- [x] 4.3 Add `_cached_checker_results` session-scoped fixture — runs `check-test-hardcodes.sh` once per mode (canonical, boundary, root), returns `MappingProxyType`
- [x] 4.4 Add `checker_result` function-scoped accessor fixture — returns cached results per mode, composes "all" mode from three cached results with correct `max()` returncode and deduplicated summary lines
- [x] 4.5 Add `_cleanup_stale_temp_files` session-scoped autouse fixture — removes `tmp*.py` from all `_CHECKER_SCAN_DIRS`
- [x] 4.6 Add `_compute_checker_hash` standalone helper — sha256 of script + all scanned .py files (exclude `__pycache__/` and `__init__.py`, deduplicate via `seen: set[Path]`)

## 5. Gatekeeper Script

- [x] 5.1 Create `scripts/` directory if it does not exist
- [x] 5.2 Create `scripts/check-test-hardcodes.sh` with 4-mode dispatcher (canonical/boundary/root/all) in `main()`
- [x] 5.3 Define 7 banned-pattern arrays: BANNED_PROD_URLS, BANNED_SECRETS, BANNED_DB_PARAMS, BANNED_GATEWAY_PORTS, BANNED_PROVIDER_TYPES, BANNED_MODEL_NAMES, BANNED_OTHER_REGEX
- [x] 5.4 Implement `check_canonical()` mode — STRICT: grep all banned patterns in `tests/unit/`, any match is a violation
- [x] 5.5 Implement `check_boundary()` mode — WHITELIST: check BANNED_PROD_URLS first (always banned), then check all fixed-string patterns with `check_boundary_annotations_fixed()` lookback algorithm (20 non-blank lines, same-line check, skip docstrings)
- [x] 5.6 Implement `check_root()` mode — STRICT: scan `tests/*.py` (root-level only, exclude subdirectories)
- [x] 5.7 Implement `EXCLUDE_FILES` list — skip conftest.py, _canonical.py, _constants.py, and all future gatekeeper test files
- [x] 5.8 Make the script executable: `chmod +x scripts/check-test-hardcodes.sh`
- [x] 5.9 Run `bash scripts/check-test-hardcodes.sh all` on the clean codebase to verify zero false positives (or add EXCLUDE_FILES entries if needed)

## 6. _BASE_ENV Deduplication

- [x] 6.1 Replace duplicated `_BASE_ENV` dict in `tests/unit/config/test_loader.py` with `CanonicalConfig.from_example_files()` helper
- [x] 6.2 Replace duplicated `_BASE_ENV` dict in `tests/unit/config/test_config_init.py` with `CanonicalConfig.from_example_files()` helper
- [x] 6.3 Replace duplicated `_BASE_ENV` dict in `tests/unit/config/test_gateway_config.py` with `CanonicalConfig.from_example_files()` helper
- [x] 6.4 Replace duplicated `_BASE_ENV` dict in remaining config test files (`test_resolve_env_vars.py`, `test_config_examples.py`, etc.)
- [x] 6.5 Verify no `_BASE_ENV` or `FULL_ENV` dictionary definitions remain: `grep -rn "_BASE_ENV\|FULL_ENV" tests/ --include='*.py' | grep -v __pycache__`
- [x] 6.6 Run `make test` to verify config tests pass after deduplication

## 7. Documentation

- [x] 7.1 Create `TESTING.md` — documentation index with links to GUIDE/RUN/GATEKEEPER, quick-start by role
- [x] 7.2 Create `TESTING-GUIDE.md` — Golden Rule (zero hardcodes), test categories, CanonicalConfig, boundary annotations, anti-patterns, compliance checklist
- [x] 7.3 Create `TESTING-RUN.md` — Makefile targets, process-isolation groups (G1-G6), timeout policy, markers, typical workflow
- [x] 7.4 Create `TESTING-GATEKEEPER.md` — script architecture (4 modes), banned-pattern arrays, cache fixtures (3-layer chain), test classification (3 tiers), enforcement layers
- [x] 7.5 Update `tests/AGENTS.md` — add `batching/`, `security/`, `stress/` to directory tree, replace stale markers with `slow`/`postgres`/`meta`, add CanonicalConfig section, link to TESTING*.md

## 8. Verification

- [x] 8.1 Run `make test` — verify G1-G5 pass, G5 now collects gatekeeper tests at root
- [x] 8.2 Run `bash scripts/check-test-hardcodes.sh all` — verify zero violations on clean codebase
- [x] 8.3 Run `poetry run pyright` — verify zero type errors in new and modified files
- [x] 8.4 Run `poetry run ruff check src/ tests/` — verify linting on changed files
- [x] 8.5 Run `grep 'pytest_addoption' tests/conftest.py` — verify the --run-postgres hook is preserved after the conftest refactor
- [x] 8.6 Run `grep 'canonical_config' tests/conftest.py` — verify CanonicalConfig fixtures are present
- [x] 8.7 Run `grep '_cached_checker_results' tests/conftest.py` — verify gatekeeper fixtures are present
- [x] 8.8 Run `ls tests/test_*.py` — verify gatekeeper test files exist at root level
- [x] 8.9 Run `ls TESTING*.md` — verify all 4 documentation files exist

## 9. Test Delegation (via @Mr.Tester)

- [x] 9.1 Read `test-plan.md` Delegation Groups section
- [x] 9.2 Delegate group `canonical-config` to @Mr.Tester (scope: tests/test_canonical_config.py, tests/test_canonical_fixtures.py, tests/test_constants.py)
- [x] 9.3 Delegate group `gatekeeper-checker-modes` to @Mr.Tester (scope: tests/test_hardcode_checker_modes.py, tests/test_hardcode_checker_patterns.py)
- [x] 9.4 Delegate group `gatekeeper-cache-fixtures` to @Mr.Tester (scope: tests/test_checker_cache_fixtures.py)
- [x] 9.5 Delegate group `gatekeeper-structural-tests` to @Mr.Tester (scope: tests/test_canonical_integrity.py, tests/test_project_structure.py, tests/test_makefile_groups.py, tests/test_secret_isolation.py, tests/test_env_example.py, tests/test_documentation_sync.py)
- [x] 9.6 Delegate group `testing-documentation` to @Mr.Tester (scope: tests/test_testing_docs.py)
- [x] 9.7 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 9.8 Re-delegate any groups affected by source fixes
- [x] 9.9 Verify all groups pass and coverage matches `test-plan.md`
