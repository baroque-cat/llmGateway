## Context

The project currently uses `typeCheckingMode: "strict"` globally in `pyrightconfig.json`, applied to both `src/` and `tests/`. This produces 3,552 pyright errors, of which only 1 is in production code (`src/services/gateway/gateway_service.py`) and ~3,551 are in test code. The test errors are dominated by strict-mode false positives: `reportUnknownMemberType` (1,249 — MagicMock chains), `reportUnknownVariableType` (433 — cascade), `reportPrivateUsage` (382 — white-box testing), and untyped pytest fixture parameters (735 combined). This noise makes pyright output unreadable and masks any real type errors in `src/`.

Simultaneously, 7 G1 unit tests fail due to a regression where `import main` was accidentally replaced with `pass` inside patched context blocks. The patch targets (`src.config.load_config`, `src.config.logging_config.setup_logging`, etc.) are all correct and resolvable — the tests simply never trigger `main.py`'s import-time side effects because they never execute `import main`.

## Goals / Non-Goals

**Goals:**
- Eliminate pyright false-positive noise from test code while preserving strict-mode checking for core domain logic and config schemas
- Fix 7 failing G1 tests so `make test` passes (885 passed, 1 xfailed)
- Keep `make typecheck` useful and readable — ~50-100 errors, all in `src/core/` and `src/config/`
- Zero changes to production code or architecture

**Non-Goals:**
- Fix ruff F821 "undefined name" errors (43 occurrences — separate plan needed)
- Fix ruff style warnings (F841, SIM117, SIM102 — ~56 occurrences)
- Clean up unnecessary `# pyright: ignore` comments (can be done incrementally later)
- Change `main.py`'s import-time side-effect pattern (intentional architecture)

## Decisions

### Decision 1: Use pyright `strict[]` array (not `executionEnvironments`)

**Chosen**: `typeCheckingMode: "basic"` globally + `"strict": ["src/core", "src/config"]`

**Alternatives considered**:
- **`executionEnvironments` with per-rule overrides**: Would require ~10 rule entries to relax non-core dirs to "warning"/"none" (~30 lines of config). Semantically "strict minus exceptions" — harder to reason about. Risk of accidentally relaxing important checks.
- **Nested `pyrightconfig.json` files**: Breaks cross-directory import resolution (`src/services/` imports from `src.core/`). Not viable for this tightly-coupled codebase.
- **Per-file `# pyright: basic` comments**: Labor-intensive (50+ files), easy to forget on new files, no central visibility.
- **`strict[]` array**: Clean semantics — "basic by default, strict where it matters." Minimal config (2 lines). Reversible — one config change restores global strict.

**Rationale**: The `strict[]` array is pyright's designed mechanism for promoting specific paths to strict mode. It works like `# pyright: strict` but at the config level. With global `basic`, only the paths in `strict[]` get the full strict rule set. Everything else gets basic mode which still checks meaningful errors (argument types, undefined variables, attribute access, optional member access) but suppresses the noise rules (unknown member types, private usage, untyped parameters).

**Why `src/core/` and `src/config/` specifically**: These directories contain the domain layer — interfaces (`IProvider`, `IResourceSyncer`, etc.), enums (`ErrorReason`, `ProviderType`), frozen DTOs (`CheckResult`, `RequestDetails`), Pydantic v2 schemas (`src/config/schemas.py` at 820 lines), and the config loader. They have zero or near-zero type-ignore comments (core: 3 ignores for narrow edge cases; config: 4 ignores for ruamel.yaml/Pydantic limitations). They benefit most from strict checking because type errors here propagate to all downstream code.

### Decision 2: Restore `import main` in tests (do not refactor `main.py`)

**Chosen**: Add `import main  # noqa: F811` in the 7 places where it was replaced with `pass`.

**Alternatives considered**:
- **Refactor `main.py` to defer side effects into an `init()` function**: Better testability, but large architectural change affecting uvicorn deployment (`uvicorn main:app` expects `app` at module level). Test docstrings explicitly document that module-level execution is the intended design after a prior refactoring.
- **Use `importlib.reload(main)`**: Works but introduces dependency on `importlib` and a fragile import order. Existing pattern (`import main` with `_remove_main_from_sys_modules` cleanup) is already established and working in 8 passing tests.
- **Move test helper `import_fresh_main()` to conftest**: Over-engineering for 7 tests. Existing inline `import main` pattern in passing tests (`test_err_05` line 137, `test_ut_m01` line 64) is clear and self-contained.

**Rationale**: The `pass` statements on lines 64, 80, 100, 118 of `test_main_error_handling.py` carry `# pyright: ignore[reportUnusedImport]  # noqa: F811` comments — these suppression comments are evidence the original code had `import main` (F811 suppresses "redefinition of unused name"). This is a pure regression fix, not an architectural issue.

## Risks / Trade-offs

- **[R1] `reportPrivateUsage` disabled for non-strict directories**: Basic mode does not check private member access. This means `src/services/` and `src/providers/` could have accidental `_private` usage go undetected. → **Mitigation**: Private member access is predominantly a test pattern (white-box testing). Production code already follows the convention of `_` prefix for private members. No known cases of accidental private access in production code. If needed, `reportPrivateUsage` can be manually enabled via `# pyright: strict` in specific files.

- **[R2] Basic mode may miss some real errors**: Basic mode disables `reportUnknownMemberType`, `reportUnknownVariableType`, `reportUnknownArgumentType`, etc. If production code in `src/services/` or `src/providers/` has genuine type errors that these rules would catch, they won't be flagged. → **Mitigation**: These rules primarily catch "unknown" types, not "wrong" types. Actual type mismatches (`reportArgumentType`, `reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess`) remain active in basic mode. The risk is confined to bugs caused by `Any`/`Unknown` types slipping through — a known trade-off of basic mode.

- **[R3] Test fixes could mask other `main.py` import issues**: If the `_remove_main_from_sys_modules` fixture ever breaks, these tests would silently pass (main already cached) instead of testing fresh import behavior. → **Mitigation**: The `_cleanup_main_module` autouse fixture runs before AND after every test, explicitly removing `main` from `sys.modules`. This is independently tested. The `test_err_05_successful_import_after_previous_failure` test already verifies that a failed import followed by a successful import works correctly — confirming the cleanup mechanism.
