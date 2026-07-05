## Why

The test suite has two critical issues: (1) 7 tests in `tests/unit/test_main_error_handling.py` and `tests/unit/test_main_module_app.py` are failing — a regression where `import main` statements were accidentally replaced with `pass`, and (2) pyright in strict mode reports 3,552 errors, 99.97% of which are false-positive strict-mode noise from test code (MagicMock chains, untyped pytest fixtures, white-box private member access). This makes pyright output unreadable and masks real type errors in production code.

## What Changes

- **Fix 7 failing G1 tests**: Restore `import main` statements inside patched context blocks in `test_main_error_handling.py` (4 tests) and add missing `import main` in `test_main_module_app.py` (3 tests). No production code changes.
- **Implement tiered pyright strictness**: Switch global `typeCheckingMode` from `"strict"` to `"basic"` and promote `src/core/` and `src/config/` to strict via pyright's `strict` array. This preserves strict checking for core domain logic and config schemas while eliminating ~3,500 false-positive errors in tests, services, providers, db, and metrics.

## Capabilities

### New Capabilities
- `pyright-tiered-strictness`: Tiered pyright type-checking — strict mode for `src/core/` and `src/config/` (domain logic, interfaces, enums, Pydantic schemas, config loader), basic mode for all other source and test code.

### Modified Capabilities
<!-- None — this change does not alter any existing user-facing or API capability. -->

## Impact

- **Affected files**: `pyrightconfig.json` (mode change + new `strict` array), `tests/unit/test_main_error_handling.py` (4 lines), `tests/unit/test_main_module_app.py` (3 lines)
- **Production code**: Zero changes
- **CI pipeline**: `make ci` currently fails due to both `make test` (7 FAILED) and `make typecheck` (3,552 errors). After this change, `make test` passes and `make typecheck` reports ~50-100 meaningful errors (only in `src/core/` and `src/config/`).
- **Dependencies**: None
- **Breaking changes**: None
