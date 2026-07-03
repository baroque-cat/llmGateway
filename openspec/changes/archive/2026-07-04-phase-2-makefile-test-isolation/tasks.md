## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b test-ref`
- [x] 1.2 Run `poetry run pytest --co -q` to verify all 1501 tests can be collected before changes

## 2. Makefile — Process-isolation test runner

- [x] 2.1 Create `Makefile` in project root with `.PHONY: lint typecheck test test-slow test-postgres test-all ci`
- [x] 2.2 Add `lint` target: `poetry run ruff check src/ tests/`
- [x] 2.3 Add `typecheck` target: `poetry run pyright`
- [x] 2.4 Add `test` target with G1-G5 groups: G1 (unit excl. config, no `-` prefix, gate), G2 (config), G3 (integration+security+e2e), G4 (batching), G5 (root-level via 6 `--ignore` flags). All with `--timeout=30 -m "not slow and not postgres"`. G2-G5 use `-` prefix for fault tolerance.
- [x] 2.5 Add `test-slow` target: G6 stress tests with `-m slow --timeout=60`
- [x] 2.6 Add `test-postgres` target: `poetry run pytest -v --run-postgres -m "postgres" || true` (handles exit 5 when 0 postgres tests exist)
- [x] 2.7 Add `test-all` target: depends on `test test-slow`, prints "All tests complete"
- [x] 2.8 Add `ci` target: `lint typecheck test` (no `-` prefix, any failure aborts)

## 3. tests/conftest.py — --run-postgres hook

- [x] 3.1 Add `import pytest` to `tests/conftest.py` (stdlib import `os` remains, `pytest` import added after)
- [x] 3.2 Add `pytest_addoption(parser)` — register `--run-postgres` CLI flag (store_true, default=False)
- [x] 3.3 Add `pytest_configure(config)` — register `postgres` marker description via `config.addinivalue_line`
- [x] 3.4 Add `pytest_collection_modifyitems(config, items)` — skip all `postgres`-marked items with reason "--run-postgres not specified" when flag is absent
- [x] 3.5 Run `poetry run pytest --co -q` to confirm no collection errors after hook addition

## 4. test_batching/ → batching/ rename

- [x] 4.1 Run `git mv tests/test_batching tests/batching` to rename with history preservation
- [x] 4.2 Run `poetry run pytest tests/batching/ --co -q` to verify all 5 test modules are discoverable at new path
- [x] 4.3 Run `grep -rn "tests.test_batching\|tests/test_batching" . --include='*.py' --include='*.toml' --include='*.yml' --include='*.md' | grep -v openspec/changes/` to confirm zero stale references (only expected hits in openspec change docs)

## 5. Verification

- [x] 5.1 Run `make test` — verify G1-G5 execute, G1 as gate (no `-`), G2-G5 fault-tolerant
- [x] 5.2 Run `make test-slow` — verify G6 stress tests execute with `--timeout=60 -m slow`
- [x] 5.3 Run `make test-postgres` — verify `--run-postgres` flag accepted, exit 0 (exit 5 swallowed by `|| true`)
- [x] 5.4 Run `make test-all` — verify `test` then `test-slow` execute, "All tests complete" printed
- [x] 5.5 Run `make -n ci` dry-run — verify order: ruff → pyright → make test, no `-` prefix
- [x] 5.6 Run `poetry run pytest --co -q` — verify 1501 tests collected, no warnings
- [x] 5.7 Run `poetry run pytest --run-postgres -m "postgres" --co -q` — verify flag accepted without error
- [x] 5.8 Run `grep 'tests/batching/' Makefile` — verify G4 references the new path
- [x] 5.9 Run `grep 'pytest_addoption' tests/conftest.py` — verify hook is present
- [x] 5.10 Run `ls tests/batching/` — verify 6 files (5 test modules + __init__.py)

## 6. Test Delegation (via @Mr.Tester)

- [x] 6.1 Read `test-plan.md` Delegation Groups section
- [x] 6.2 Delegate group `makefile-static-checks` to @Mr.Tester (scope: Makefile content inspection)
- [x] 6.3 Delegate group `makefile-execution` to @Mr.Tester (scope: Makefile target execution/dry-run)
- [x] 6.4 Delegate group `conftest-postgres-hook` to @Mr.Tester (scope: tests/conftest.py hook verification)
- [x] 6.5 Delegate group `batching-rename` to @Mr.Tester (scope: tests/batching/ directory + stale reference grep)
- [x] 6.6 Review @Mr.Tester reports and fix any issues found
- [x] 6.7 Re-delegate any groups affected by fixes
- [x] 6.8 Verify all groups pass and coverage matches `test-plan.md`
