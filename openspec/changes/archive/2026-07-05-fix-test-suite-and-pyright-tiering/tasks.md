## 1. Git & Environment

- [x] 1.1 Create a new git branch: `git checkout -b test-ref`
- [x] 1.2 Run the full test suite to capture baseline failures: `make test 2>&1 | tee baseline_test.log`

## 2. Implementation — pyrightconfig.json Tiering

- [x] 2.1 Apply tiered pyright configuration in `pyrightconfig.json`:
  - Change `"typeCheckingMode": "strict"` to `"typeCheckingMode": "basic"`
  - Add `"strict": ["src/core", "src/config"]` as a top-level field
  - Add `"src/core/http2"` to the existing `exclude` array (temporary backport package, not for strict checking)
  - Set `"reportUnnecessaryTypeIgnoreComment": false` (avoids noise from stale `# pyright: ignore` comments remaining after mode switch; see R8 in test-plan)
- [x] 2.2 Verify pyright exits cleanly: `poetry run pyright` — expect ~50-100 errors in `src/core/` and `src/config/` only, zero errors in `tests/`
- [x] 2.3 Verify typecheck passes CI gate: `make typecheck` exits zero

## 3. Implementation — Fix 7 Failing G1 Tests

- [x] 3.1 Fix `tests/unit/test_main_error_handling.py` — replace `pass` with `import main` in 4 tests:
  - Line 64 (`test_err_01`): `pass  # pyright: ignore[reportUnusedImport]  # noqa: F811` → `import main  # noqa: F811`
  - Line 80 (`test_err_02`): same replacement
  - Line 100 (`test_err_03`): same replacement
  - Line 118 (`test_err_04`): same replacement
- [x] 3.2 Fix `tests/unit/test_main_module_app.py` — add missing `import main` in 3 tests:
  - `test_ut_m02`: add `import main  # noqa: F811` after the `with(...):` block and before `mock_load.assert_called_once()`
  - `test_ut_m03`: add `import main  # noqa: F811` after the `with(...):` block and before `mock_setup.assert_called_once_with(...)`
  - `test_ut_m04`: add `import main  # noqa: F811` after the `with(...):` block and before `mock_create.assert_called_once_with(...)`
- [x] 3.3 Verify the 7 tests now pass: `poetry run pytest tests/unit/test_main_error_handling.py tests/unit/test_main_module_app.py -v --timeout=30`
- [x] 3.4 Verify full G1 suite passes: `poetry run pytest tests/unit/ --ignore=tests/unit/config -q --timeout=30 -m "not slow and not postgres"`

## 4. Infrastructure — Gatekeeper Registration

- [x] 4.1 Register new test files in `scripts/check-test-hardcodes.sh`: add `"test_pyright_tiered_config.py"` and `"test_pyright_ci_gate.py"` to the `EXCLUDE_FILES` bash array
- [x] 4.2 Register new test files in `tests/test_hardcode_checker_regression.py`: add `"test_pyright_tiered_config.py"` and `"test_pyright_ci_gate.py"` to the `_GATEKEEPER_TEST_FILES` list
- [x] 4.3 Verify gatekeeper passes: `bash scripts/check-test-hardcodes.sh all && poetry run pytest tests/test_hardcode_checker_regression.py -v --timeout=30`

## 5. Testing — Delegate to @Mr.Tester

> **CRITICAL TEST DELEGATION PROTOCOL**: When delegating to @Mr.Tester for ANY group below, you MUST pass the following project testing documentation as context with EVERY delegation:
> - `AGENTS.md` — project conventions, naming, typing style
> - `TESTING.md` — test directory structure, quick start, test categories
> - `TESTING-RUN.md` — Makefile targets, G1-G6 process-isolation groups, timeout policy, markers
> - `TESTING-GUIDE.md` — Golden Rule (CanonicalConfig), boundary annotations, anti-patterns, compliance checklist
> - `TESTING-GATEKEEPER.md` — gatekeeper architecture, banned-pattern arrays, boundary lookback, cache fixtures
>
> These docs are MANDATORY context for every @Mr.Tester invocation in this change. The agents must understand the project's testing conventions before writing or modifying any tests.

- [x] 5.1 Read `test-plan.md` Delegation Groups section to understand group assignments
- [x] 5.2 Delegate group `g5-pyright-tiered-strictness` to @Mr.Tester (scope: `tests/test_pyright_tiered_config.py` — NEW, 9 scenario tests for config format + strict/basic mode behavior). Pass AGENTS.md, TESTING.md, TESTING-RUN.md, TESTING-GUIDE.md, TESTING-GATEKEEPER.md.
- [x] 5.3 Delegate group `g5-ci-gate-verification` to @Mr.Tester (scope: `tests/test_pyright_ci_gate.py` — NEW, 2 scenario tests for CI gate + prod code invariant). Pass AGENTS.md, TESTING.md, TESTING-RUN.md, TESTING-GUIDE.md, TESTING-GATEKEEPER.md.
- [x] 5.4 Delegate group `g1-main-import-regression` to @Mr.Tester (scope: `tests/unit/test_main_error_handling.py`, `tests/unit/test_main_module_app.py` — MODIFY, verify 7 fixes pass and no regressions). Pass AGENTS.md, TESTING.md, TESTING-RUN.md, TESTING-GUIDE.md, TESTING-GATEKEEPER.md.
- [x] 5.5 Delegate group `g5-gatekeeper-registry-update` to @Mr.Tester (scope: `tests/test_hardcode_checker_regression.py`, `scripts/check-test-hardcodes.sh` — MODIFY, verify registration). Pass AGENTS.md, TESTING.md, TESTING-RUN.md, TESTING-GUIDE.md, TESTING-GATEKEEPER.md.
- [x] 5.6 Review @Mr.Tester reports from all 4 groups and fix any source-level bugs discovered
- [x] 5.7 Re-delegate any groups affected by source fixes

## 6. Final Verification

- [x] 6.1 Run `make test` — G1: 885 passed/1 xfailed ✅, G2: 304 passed ✅, G5: 157 passed ✅ (incl. 11 new tests). G3: 23 failed (pre-existing TypeError MagicMock>int in gateway_service.py:934), G4: 2 failed (pre-existing timeouts) — both unrelated to this change (no src/ or G3/G4 test files modified)
- [x] 6.2 Run `make typecheck` — pyright exits clean: 0 errors, 0 warnings, 0 informations ✅
- [x] 6.3 Run `make lint` — 99 ruff errors, all pre-existing (F821×43, F841×16, SIM117×15, SIM102×7, SIM105×2, SIM103×1, B018×2, E402×1). No F401 errors (fixed). 99 = baseline count ✅
- [x] 6.4 Run `make ci` — `make ci` = lint→typecheck→test. Lint fails (99 pre-existing errors, exit 2), CI stops at lint. Typecheck (0 errors) and test G1 (885 passed) verified separately. Expected per plan — ruff out of scope.
- [x] 6.5 Verify git diff: no files under `src/` modified, `main.py` unchanged ✅. Modified: pyrightconfig.json, 2 test files, gatekeeper script+regression test. New: 2 test files, openspec change dir, baseline_test.log.

<!--
  TEST ORCHESTRATION PROTOCOL (followed by the apply phase agent):

  1. Read test-plan.md → Delegation Groups section
  2. For EACH of the 4 groups listed in section 5, launch one @Mr.Tester subagent:
     - g5-pyright-tiered-strictness: write NEW tests/test_pyright_tiered_config.py
     - g5-ci-gate-verification: write NEW tests/test_pyright_ci_gate.py
     - g1-main-import-regression: MODIFY existing tests, verify fixes
     - g5-gatekeeper-registry-update: MODIFY infrastructure files
  3. EVERY @Mr.Tester invocation MUST include AGENTS.md, TESTING.md, TESTING-RUN.md,
     TESTING-GUIDE.md, TESTING-GATEKEEPER.md as context files to read.
  4. Launch ALL 4 groups IN PARALLEL (single message with 4 task calls)
  5. After all testers return: fix any reported source bugs, re-delegate affected groups
  6. Repeat until all groups pass
-->
