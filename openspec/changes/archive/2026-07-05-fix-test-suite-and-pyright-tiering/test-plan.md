# QA Strategy & Test Plan

> **Change:** `fix-test-suite-and-pyright-tiering`
> **Spec Capability:** `pyright-tiered-strictness`
> **Process-Isolation Groups:** G1 (unit tests), G5 (root-level structural tests)
> **Test Framework:** pytest ≥9.0 with `pytest-asyncio`, `pytest-cov`, `pytest-timeout`

---

## Coverage Map

Every `#### Scenario:` in the spec is mapped to a concrete test file, test function/class, and delegation group. Test file placement follows the project's actual directory structure documented in `TESTING.md` and `tests/AGENTS.md`:

- **G1** (`tests/unit/`): unit tests for `main.py` import behavior — the 7 failing tests
- **G5** (`tests/test_*.py`): root-level structural/gatekeeper tests — pyright config verification

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | pyright-tiered-strictness | Core domain logic is type-checked in strict mode | Pyright reports errors for type mismatches in src/core/ | `tests/test_pyright_tiered_config.py` | `TestPyrightStrictModeBehavior::test_strict_mode_reports_type_mismatch_in_core` | g5-pyright-tiered-strictness |
| 2 | pyright-tiered-strictness | Core domain logic is type-checked in strict mode | Pyright reports unknown member access in src/core/ | `tests/test_pyright_tiered_config.py` | `TestPyrightStrictModeBehavior::test_strict_mode_reports_unknown_member_in_core` | g5-pyright-tiered-strictness |
| 3 | pyright-tiered-strictness | Core domain logic is type-checked in strict mode | Pyright reports private member access in src/core/ | `tests/test_pyright_tiered_config.py` | `TestPyrightStrictModeBehavior::test_strict_mode_reports_private_usage_in_core` | g5-pyright-tiered-strictness |
| 4 | pyright-tiered-strictness | Non-core source code is type-checked in basic mode | Basic mode still catches argument type mismatches | `tests/test_pyright_tiered_config.py` | `TestPyrightBasicModeBehavior::test_basic_mode_catches_argument_type_mismatch` | g5-pyright-tiered-strictness |
| 5 | pyright-tiered-strictness | Non-core source code is type-checked in basic mode | Basic mode still catches undefined variables | `tests/test_pyright_tiered_config.py` | `TestPyrightBasicModeBehavior::test_basic_mode_catches_undefined_variable` | g5-pyright-tiered-strictness |
| 6 | pyright-tiered-strictness | Non-core source code is type-checked in basic mode | Basic mode does not report unknown member types from MagicMock | `tests/test_pyright_tiered_config.py` | `TestPyrightBasicModeBehavior::test_basic_mode_suppresses_magicmock_unknown_member` | g5-pyright-tiered-strictness |
| 7 | pyright-tiered-strictness | Non-core source code is type-checked in basic mode | Basic mode does not report untyped pytest fixture parameters | `tests/test_pyright_tiered_config.py` | `TestPyrightBasicModeBehavior::test_basic_mode_suppresses_untyped_fixture_params` | g5-pyright-tiered-strictness |
| 8 | pyright-tiered-strictness | Non-core source code is type-checked in basic mode | Basic mode does not report deliberate private member access in tests | `tests/test_pyright_tiered_config.py` | `TestPyrightBasicModeBehavior::test_basic_mode_suppresses_private_usage_in_tests` | g5-pyright-tiered-strictness |
| 9 | pyright-tiered-strictness | Tiered configuration is defined in a single pyrightconfig.json | Configuration format | `tests/test_pyright_tiered_config.py` | `TestPyrightConfigFormat::test_pyrightconfig_has_tiered_format` | g5-pyright-tiered-strictness |
| 10 | pyright-tiered-strictness | CI pipeline remains operational | make ci passes after implementation | `tests/test_pyright_ci_gate.py` | `TestPyrightCiGate::test_pyright_exits_zero_after_tiering` | g5-ci-gate-verification |
| 11 | pyright-tiered-strictness | Test suite passes with all 7 previously-failing G1 tests fixed | test_err_01 through test_err_04 pass | `tests/unit/test_main_error_handling.py` | `TestConfigErrorBlocksModuleImport::test_err_01_file_not_found_blocks_import` (+ `test_err_02`, `test_err_03`, `test_err_04`) | g1-main-import-regression |
| 12 | pyright-tiered-strictness | Test suite passes with all 7 previously-failing G1 tests fixed | test_ut_m02 through test_ut_m04 pass | `tests/unit/test_main_module_app.py` | `TestModuleLevelApp::test_ut_m02_load_config_called_on_import` (+ `test_ut_m03`, `test_ut_m04`) | g1-main-import-regression |
| 13 | pyright-tiered-strictness | Production code is not modified | Zero production code changes | `tests/test_pyright_ci_gate.py` | `TestPyrightCiGate::test_no_production_code_modified` | g5-ci-gate-verification |

---

## Delegation Groups

Groups are non-overlapping by test file. Each group maps to a process-isolation group (G1 or G5) from `TESTING-RUN.md`. Groups can be executed in parallel by separate agents.

### Group: g1-main-import-regression

**Process-Isolation Group:** G1 (unit tests, gate — failure stops `make test`)
**Scope:** `tests/unit/test_main_error_handling.py`, `tests/unit/test_main_module_app.py`
**Rationale:** Both files test `main.py` import-time side effects and share the same `_remove_main_from_sys_modules` cleanup pattern. The fix is identical in nature (restore `import main` statements). These are the 7 previously-failing tests that block the G1 gate.

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/test_main_error_handling.py` | 1 (scenario #11: test_err_01 through test_err_05 pass) | MODIFY |
| `tests/unit/test_main_module_app.py` | 1 (scenario #12: test_ut_m02 through test_ut_m04 pass) | MODIFY |

**Verification command:**
```bash
poetry run pytest tests/unit/test_main_error_handling.py tests/unit/test_main_module_app.py -v --timeout=30
```

---

### Group: g5-pyright-tiered-strictness

**Process-Isolation Group:** G5 (root-level structural tests, fault-tolerant)
**Scope:** `tests/test_pyright_tiered_config.py`
**Rationale:** All pyright config format and tiered-mode behavior tests live in a single new file. Uses a class-scoped fixture that creates a synthetic temp project (mimicking the project's `pyrightconfig.json`) and runs pyright once, then each test function asserts on specific parts of the JSON output. This follows the established "Tier 2: Synthetic violation tests" pattern from `TESTING-GATEKEEPER.md` and the subprocess-pyright pattern from `tests/security/test_transparent_error_security.py`.

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_pyright_tiered_config.py` | 9 (scenarios #1–#9) | NEW |

**Test class structure:**
- `TestPyrightConfigFormat` — scenario #9 (parse actual `pyrightconfig.json`, no subprocess)
- `TestPyrightStrictModeBehavior` — scenarios #1–#3 (synthetic temp files in `src/core/`, pyright run)
- `TestPyrightBasicModeBehavior` — scenarios #4–#8 (synthetic temp files in `src/services/` and `tests/`, pyright run)

**Verification command:**
```bash
poetry run pytest tests/test_pyright_tiered_config.py -v --timeout=30 -m "not slow and not postgres"
```

---

### Group: g5-ci-gate-verification

**Process-Isolation Group:** G5 (root-level structural tests, fault-tolerant)
**Scope:** `tests/test_pyright_ci_gate.py`
**Rationale:** CI pipeline gate verification (pyright exit code) and production-code invariant check (git diff). These are change-level invariants that verify the implementation did not modify production code and that pyright passes after tiering. Separate from `test_pyright_tiered_config.py` because these tests run pyright on the ACTUAL project (not a synthetic temp project) and inspect git state.

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_pyright_ci_gate.py` | 2 (scenarios #10, #13) | NEW |

**Test class structure:**
- `TestPyrightCiGate` — scenario #10 (run `poetry run pyright` on actual project, assert exit code 0 or warnings-only) + scenario #13 (git diff check for zero production code changes)

**Verification command:**
```bash
poetry run pytest tests/test_pyright_ci_gate.py -v --timeout=30 -m "not slow and not postgres"
```

---

### Group: g5-gatekeeper-registry-update

**Process-Isolation Group:** G5 (root-level structural tests, fault-tolerant)
**Scope:** `tests/test_hardcode_checker_regression.py`, `scripts/check-test-hardcodes.sh`
**Rationale:** Adding new root-level test files (`test_pyright_tiered_config.py`, `test_pyright_ci_gate.py`) requires registering them in the gatekeeper's `EXCLUDE_FILES` array and in the `_GATEKEEPER_TEST_FILES` list. The existing `test_exclude_files_covers_all_gatekeeper_tests` regression test verifies that all gatekeeper test files are listed in `EXCLUDE_FILES` — it will fail if the new files are not registered. This is a necessary infrastructure update, not a spec-scenario test.

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_hardcode_checker_regression.py` | 0 (infrastructure: update `_GATEKEEPER_TEST_FILES` list) | MODIFY |
| `scripts/check-test-hardcodes.sh` | 0 (infrastructure: update `EXCLUDE_FILES` array) | MODIFY |

**Verification command:**
```bash
bash scripts/check-test-hardcodes.sh all && poetry run pytest tests/test_hardcode_checker_regression.py -v --timeout=30
```

---

## Test Modifications

### Spec-Mandated Test Fixes (7 failing tests)

| File | Change | Reason |
|---|---|---|
| `tests/unit/test_main_error_handling.py` | Replace `pass  # pyright: ignore[reportUnusedImport]  # noqa: F811` with `import main  # noqa: F811` on **4 lines** (lines 64, 80, 100, 118) inside `test_err_01`, `test_err_02`, `test_err_03`, `test_err_04`. The `pass` statement replaced the original `import main` during a regression — the `# noqa: F811` suppression comment is evidence that `import main` was the original code (F811 = "redefinition of unused name"). Without `import main`, the patched context blocks never trigger `main.py`'s import-time side effects, so the `pytest.raises()` context never catches anything. | Spec scenario #11 ("test_err_01 through test_err_04 pass") + Design Decision 2 ("Restore `import main` in tests"). The tests assert that config loading errors (FileNotFoundError, ValueError, SystemExit, generic Exception) block the module import, but without `import main` the import never happens. |
| `tests/unit/test_main_module_app.py` | Add `import main  # noqa: F811` inside the `with (...)` context blocks in `test_ut_m02` (after line 91, before `mock_load.assert_called_once()`), `test_ut_m03` (after line 108, before `mock_setup.assert_called_once_with(...)`), and `test_ut_m04` (after line 126, before `mock_create.assert_called_once_with(...)`). **3 lines** total. The `import main` statement is entirely missing — not even a `pass` placeholder. | Spec scenario #12 ("test_ut_m02 through test_ut_m04 pass") + Design Decision 2. These tests assert that `load_config()`, `setup_logging()`, and `create_app()` are called during import, but without `import main` the mocks are never triggered. The existing `test_ut_m01` (line 64) and `test_err_05` (line 137) already have the correct `import main  # noqa: F811` pattern — the 3 missing tests should match. |

### Infrastructure Updates (required by new test files)

| File | Change | Reason |
|---|---|---|
| `tests/test_hardcode_checker_regression.py` | Add `"test_pyright_tiered_config.py"` and `"test_pyright_ci_gate.py"` to the `_GATEKEEPER_TEST_FILES` list (line ~99–126). | The `test_exclude_files_covers_all_gatekeeper_tests` test (S24) verifies that every file in `_GATEKEEPER_TEST_FILES` appears in the checker script's `EXCLUDE_FILES` array. New root-level test files must be registered or this regression test fails. |
| `scripts/check-test-hardcodes.sh` | Add `"test_pyright_tiered_config.py"` and `"test_pyright_ci_gate.py"` to the `EXCLUDE_FILES` bash array. | The hardcode checker self-excludes all root-level `test_*.py` files. New files must be listed in `EXCLUDE_FILES` to be skipped during `root` mode scanning. Without this, `bash scripts/check-test-hardcodes.sh root` may flag the new files if they contain any banned patterns. |

### Configuration Change (the implementation itself, not a test)

| File | Change | Reason |
|---|---|---|
| `pyrightconfig.json` | Change `"typeCheckingMode": "strict"` to `"typeCheckingMode": "basic"`. Add `"strict": ["src/core", "src/config"]` as a top-level field. Add `"src/core/http2"` to the `exclude` array (temporary backport package). Remove the individual `reportUnknown*` and `reportPrivateUsage` boolean overrides (they are now controlled by the mode). | Spec requirement: "Tiered configuration is defined in a single pyrightconfig.json" + Design Decision 1. The `strict[]` array is pyright's designed mechanism for promoting specific paths to strict mode. `src/core/http2/` is excluded per the spec ("excludes `src/core/http2/` which is a temporary backport package expected to be removed"). |

---

## Risks & Edge Cases

Extracted from `design.md` Risks section, plus implementation-specific edge cases identified during test plan creation.

- **[R1: reportPrivateUsage disabled for non-strict directories]** Basic mode does not check private member access. `src/services/` and `src/providers/` could have accidental `_private` usage go undetected. → **Proposed test:** `TestPyrightBasicModeBehavior::test_basic_mode_suppresses_private_usage_in_services` — create a synthetic temp file in `src/services/` that accesses a `_private` member from another class, run pyright, verify `reportPrivateUsage` is NOT reported. This confirms the trade-off is understood. (Note: this is an ADDITIONAL edge-case test beyond the 13 spec scenarios, covering the risk mitigation evidence.)

- **[R2: Basic mode may miss Unknown-typed errors]** Basic mode disables `reportUnknownMemberType`, `reportUnknownVariableType`, `reportUnknownArgumentType`. If production code in `src/services/` or `src/providers/` has genuine type errors involving `Any`/`Unknown` types, they won't be flagged. → **Proposed test:** `TestPyrightBasicModeBehavior::test_basic_mode_suppresses_unknown_variable_type` — create a synthetic temp file in `src/services/` with an `Unknown`-typed variable (e.g., `x = some_untyped_call()`), run pyright, verify `reportUnknownVariableType` is NOT reported. Pair with scenario #4 (`test_basic_mode_catches_argument_type_mismatch`) to confirm that `reportArgumentType` IS still caught — the "wrong type" vs "unknown type" distinction.

- **[R3: Test fixes could mask main.py import issues]** If the `_remove_main_from_sys_modules` fixture ever breaks, the 7 fixed tests would silently pass (`main` already cached in `sys.modules` from a previous test) instead of testing fresh import behavior. → **Proposed test:** Verify that `_remove_main_from_sys_modules()` actually removes `main` from `sys.modules` after a successful import. The existing `test_err_05_successful_import_after_previous_failure` (line 120–163) partially covers this — it asserts `"main" not in sys.modules` after a failed import (line 141). A dedicated edge-case test should also assert `"main" not in sys.modules` after a SUCCESSFUL import + cleanup, confirming the autouse `_cleanup_main_module` fixture's teardown phase works.

- **[R4: src/core/http2/ exclusion from strict mode]** The spec says `src/core/http2/` is excluded from strict mode ("a temporary backport package expected to be removed"), but the config format scenario (#9) only checks for `"strict": ["src/core", "src/config"]`. Since `src/core/http2/` is a subdirectory of `src/core/`, it would inherit strict mode unless explicitly excluded via the `exclude` array. → **Proposed test:** `TestPyrightConfigFormat::test_pyrightconfig_excludes_http2_backport` — parse `pyrightconfig.json`, verify the `exclude` array contains `"src/core/http2"` or `"**/http2"`. This ensures the temporary backport package is not type-checked in strict mode (it has its own internal type issues that would generate noise).

- **[R5: pyright subprocess timeout in G5]** Running `poetry run pyright` as a subprocess inside a test takes ~5 seconds. The G5 group has a 30-second per-test timeout. If multiple pyright runs are needed (config behavior tests + CI gate test), the total time could approach the timeout. → **Mitigation:** Use a class-scoped fixture in `test_pyright_tiered_config.py` that runs pyright ONCE on a synthetic temp project and caches the JSON output. All 8 behavior test functions (scenarios #1–#8) share the single run. The CI gate test in `test_pyright_ci_gate.py` runs pyright once on the actual project. Total: 2 pyright runs across all new tests, each well within the 30s timeout.

- **[R6: Test count drift from spec's "885 passed" assertion]** The spec scenario #10 asserts `make test SHALL report 885 passed, 1 xfailed, 0 failed`. Adding new test files (~12 new test functions across 2 new files) will increase the total count beyond 886. → **Mitigation:** The CI gate test (`test_pyright_exits_zero_after_tiering`) should assert `pyright` exit code 0 and parse the pyright output for zero errors. It should NOT assert a specific pytest test count (which is fragile and changes with every new test). The "0 failed" invariant is implicitly verified by the test suite itself passing — if any test fails, `make test` exits non-zero and CI fails. The spec's "885 passed" figure represents the pre-test-plan baseline (878 passed + 7 fixed = 885); after adding new tests, the count will be 885 + N new tests.

- **[R7: Nested pyrightconfig.json files breaking import resolution]** Design Decision 1 explicitly rejects nested `pyrightconfig.json` files because they "break cross-directory import resolution (`src/services/` imports from `src.core/`)." → **Proposed test:** `TestPyrightConfigFormat::test_no_nested_pyrightconfig_files` — scan the repository for any `pyrightconfig.json` files outside the root directory and assert none exist. This prevents a future developer from accidentally creating a nested config that breaks import resolution.

- **[R8: Stale `# pyright: ignore` comments after mode change]** The current codebase has `# pyright: ignore[reportUnknownMemberType]`, `# pyright: ignore[reportPrivateUsage]`, and `# pyright: ignore[reportUnusedImport]` comments scattered across test files. After switching to basic mode, some of these ignores become unnecessary (basic mode already suppresses those rules). Pyright's `reportUnnecessaryTypeIgnoreComment` is enabled in the current config. → **Mitigation:** This is a Non-Goal per the design doc ("Clean up unnecessary `# pyright: ignore` comments — can be done incrementally later"). The `reportUnnecessaryTypeIgnoreComment` setting should be set to `false` in the new config (or the comments will generate warnings). No dedicated test needed — this is tracked as incremental cleanup.
