# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|-----------------|-------------|----------|-----------|-----------|-------|
| S1 | `makefile-test-runner` | Makefile provides process-isolated test groups | `make test` runs G1 through G5 | `Makefile` (target: `test`) | `make-test-runs-g1-g5` — VERIFY: run `make test`; via `make -n test` dry-run confirm G1 has no `-` prefix (gate), G2-G5 have `-` prefix (fault tolerance), all 5 groups carry `--timeout=30` and `-m "not slow and not postgres"`; confirm G1 failure aborts subsequent groups, G2-G5 failures do not. | `makefile-execution` |
| S2 | `makefile-test-runner` | Makefile provides process-isolated test groups | `make test-slow` runs G6 stress tests only | `Makefile` (target: `test-slow`) | `make-test-slow-runs-g6` — VERIFY: `make -n test-slow` dry-run shows `tests/stress/` with `--timeout=60` and `-m slow`; run `make test-slow` (~7 min, 12 files); confirm G6 absent from `make test` target (dry-run of `make test` shows no `tests/stress/`). | `makefile-execution` |
| S3 | `makefile-test-runner` | Makefile provides process-isolated test groups | G5 collects root-level tests via inversion | `Makefile` (target: G5 line) | `g5-inversion-ignores` — CHECK: `grep` Makefile G5 command for exactly 6 `--ignore` flags: `tests/unit/`, `tests/integration/`, `tests/security/`, `tests/e2e/`, `tests/stress/`, `tests/batching/`; confirm remaining root-level `.py` files under `tests/` are collected (currently 0 test files at root — collection exits cleanly). | `makefile-static-checks` |
| S4 | `makefile-test-runner` | Makefile provides process-isolated test groups | `make test-postgres` runs postgres-marked tests | `Makefile` (target: `test-postgres`) | `make-test-postgres-flag` — VERIFY: `make -n test-postgres` dry-run shows `--run-postgres` and `-m "postgres"`; run `make test-postgres` (note: 0 `@pytest.mark.postgres` tests currently exist → pytest exit 5 "no tests ran" is expected; target handles this gracefully). | `makefile-execution` |
| S5 | `makefile-test-runner` | Makefile provides process-isolated test groups | `make test-all` runs full suite | `Makefile` (target: `test-all`) | `make-test-all-chains` — VERIFY: run `make test-all`; confirm G1-G5 (`make test`) execute first, then G6 (`make test-slow`); grep stdout for exact string "All tests complete" on success. | `makefile-execution` |
| S6 | `makefile-test-runner` | Makefile provides process-isolated test groups | `make ci` runs lint, typecheck, and test | `Makefile` (target: `ci`) | `make-ci-pipeline` — VERIFY: `make -n ci` dry-run shows `poetry run ruff check src/ tests/` → `poetry run pyright` → `make test` in order, with NO `-` prefix on any ci sub-step; confirm any single failure aborts the pipeline. | `makefile-execution` |
| S7 | `makefile-test-runner` | --run-postgres CLI hook enables opt-in postgres tests | Postgres tests are skipped by default | `tests/conftest.py` | `postgres-skipped-by-default` — CHECK + VERIFY: `grep` conftest.py for `pytest_addoption` registering `--run-postgres` and `pytest_collection_modifyitems` applying skip with reason "--run-postgres not specified"; run `poetry run pytest tests/unit/ --co -q` without `--run-postgres` → no collection errors. | `conftest-postgres-hook` |
| S8 | `makefile-test-runner` | --run-postgres CLI hook enables opt-in postgres tests | Postgres tests execute with --run-postgres flag | `tests/conftest.py` | `postgres-executes-with-flag` — VERIFY: run `poetry run pytest --run-postgres -m "postgres" --co -q` → flag accepted without `unrecognized argument` error. | `conftest-postgres-hook` |
| S9 | `makefile-test-runner` | test_batching directory is renamed to batching | Batching tests are discoverable at new path | `tests/batching/` | `batching-discoverable-new-path` — CHECK + VERIFY: `ls tests/batching/` shows 5 test modules plus `__init__.py`; run `poetry run pytest tests/batching/ --co -q` → 0 import errors; confirm `tests/test_batching/` no longer exists. | `batching-rename` |
| S10 | `makefile-test-runner` | test_batching directory is renamed to batching | No references to the old path remain | repo-wide (grep) | `no-old-path-references` — CHECK: `grep -rn "tests\.test_batching\|tests/test_batching" .` returns zero hits outside `openspec/changes/phase-2-makefile-test-isolation/`. | `batching-rename` |

## Delegation Groups

Four non-overlapping groups, separated by verification type.

### Group 1: `makefile-static-checks`

**Scope:** `Makefile` (raw content inspection only)

| Test File | Scenarios | Action |
|-----------|-----------|--------|
| `Makefile` | 1 (S3) | CHECK — grep G5 command line for the 6 `--ignore` flags and root-level collection pattern |

### Group 2: `makefile-execution`

**Scope:** Makefile target execution (no direct file reads; uses `make -n` dry-run output + `make <target>` runs)

| Test File (target) | Scenarios | Action |
|--------------------|-----------|--------|
| `make test` (G1-G5) | 1 (S1) | VERIFY — `make -n test` dry-run + `make test` execution |
| `make test-slow` (G6) | 1 (S2) | VERIFY — `make -n test-slow` dry-run + `make test-slow` execution |
| `make test-postgres` | 1 (S4) | VERIFY — `make -n test-postgres` dry-run + `make test-postgres` execution |
| `make test-all` | 1 (S5) | VERIFY — `make test-all` execution + grep "All tests complete" |
| `make ci` | 1 (S6) | VERIFY — `make -n ci` dry-run + `make ci` execution |

### Group 3: `conftest-postgres-hook`

**Scope:** `tests/conftest.py`

| Test File | Scenarios | Action |
|-----------|-----------|--------|
| `tests/conftest.py` | 2 (S7, S8) | CHECK — grep for `pytest_addoption`/`pytest_collection_modifyitems`; VERIFY — run `pytest` with and without `--run-postgres` |

### Group 4: `batching-rename`

**Scope:** `tests/batching/` directory + repo-wide grep for stale path references

| Test File | Scenarios | Action |
|-----------|-----------|--------|
| `tests/batching/` | 1 (S9) | CHECK — `ls` for 5 modules + `__init__.py`; VERIFY — `pytest tests/batching/ --co -q` |
| repo-wide grep | 1 (S10) | CHECK — `grep -rn "test_batching"` returns 0 hits outside openspec change dir |

## Test Modifications

No existing `test_*.py` test files are modified in Phase 2. Changes are configuration/structural only:

| Artifact | Change Type | Reason (spec / design reference) |
|----------|-------------|----------------------------------|
| `Makefile` (new) | Created | S1-S6: 5 targets with 6 process-isolated groups |
| `tests/conftest.py` | Modified (add hook, no test functions) | S7, S8: `pytest_addoption("--run-postgres")` + `pytest_collection_modifyitems` |
| `tests/test_batching/` → `tests/batching/` | Renamed (`git mv`) | S9, S10: naming convention alignment |

Existing tests re-verify correctness via re-run through the new Makefile groups.

## Risks & Edge Cases

| # | Risk | Coverage Check | Group |
|---|------|----------------|-------|
| R1 | `--timeout=30` kills legitimate test in G1-G5 | Run `make test` → assert 0 `TimeoutError` failures | `makefile-execution` |
| R2 | `--ignore` flags miss a new directory | `ls -d tests/*/` diff against Makefile G5 `--ignore` flags | `makefile-static-checks` |
| R3 | `-` prefix hides G2-G5 failures | `make ci` has NO `-` prefixes (CI catches everything) | `makefile-execution` |
| R4 | `pytest_addoption` conflicts with plugins | `pytest --help | grep run-postgres` + `pytest --co -q` | `conftest-postgres-hook` |
| R5 | `git mv` breaks CI references | `grep -rn "test_batching" .github/ pyproject.toml` returns 0 | `batching-rename` |
| R6 | `make` not available | `which make` returns path | `makefile-execution` |
| R7 | `make test-postgres` exits 5 (no postgres tests) | Target handles exit 5 gracefully | `makefile-execution` |
| R8 | G5 collects 0 tests (no root-level test files yet) | G5 has `-` prefix in `make test`; `make ci` calls `make test` (which swallows exit 5) | `makefile-static-checks` + `makefile-execution` |
