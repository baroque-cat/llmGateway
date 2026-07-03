## Why

Phase 1 stabilized the test suite (fixed async event loop hangs, added global per-test timeout, completed the env var chain), but there is no standard way to run tests — developers invoke a single `poetry run pytest` that dumps all 1501 tests into one process with one event loop. This slows down development, makes it hard to isolate failures, and leaves stress tests (real HTTP/2 servers, 7 minutes runtime) mixed into the same invocation.

## What Changes

- **`Makefile`** (NEW): Process-isolation test runner with 5 targets (`test`, `test-slow`, `test-postgres`, `test-all`, `ci`) and 6 test groups (G1-G6). Each group is a separate `poetry run pytest` invocation with a fresh asyncio event loop, preventing cross-contamination. Groups use marker filters (`-m "not slow and not postgres"`) and per-group `--timeout` overrides. Copied from copium's Makefile paradigm, adapted for single-package monorepo.
- **`tests/conftest.py`**: Add `pytest_addoption`, `pytest_configure`, `pytest_collection_modifyitems` hooks for `--run-postgres` CLI flag. Postgres-marked tests are skipped unless the flag is passed, enabling a `make test-postgres` target.
- **`tests/test_batching/` → `tests/batching/`**: Rename directory to match the naming convention of all other test subdirectories (`unit/`, `integration/`, `e2e/`, `security/`, `stress/`). Zero import changes needed — all files import from `src.*`, none reference `tests.test_batching`.
- **`tests/stress/conftest.py`**: No changes. Verification-only to confirm Phase 1 async event loop fix works end-to-end with the new Makefile G6 group.

## Capabilities

### New Capabilities
- `makefile-test-runner`: Makefile-driven process-isolation test execution with 6 groups (G1-G5 unit/integration/batching/gatekeeper, G6 stress), custom CLI hooks (`--run-postgres`), and CI targets (`lint`, `typecheck`, `ci`).

### Modified Capabilities
<!-- None — this phase adds orchestration infrastructure without changing existing spec-level behavior. -->

## Impact

- **`Makefile`** — new file, ~50 lines. 5 `.PHONY` targets: `lint`, `typecheck`, `test`, `test-slow`, `test-postgres`, `test-all`, `ci`.
- **`tests/conftest.py`** — adds 3 functions (~30 lines) after existing `_setup_default_env_vars()`. Adds `import pytest`.
- **`tests/test_batching/` → `tests/batching/`** — directory rename, 0 code changes. 6 files move with git history via `git mv`.
- **`tests/stress/conftest.py`** — no changes, verification-only.
- No production code, no database schema, no API changes. Pure test infrastructure and build orchestration.
