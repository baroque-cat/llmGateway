## Why

After Phase 5, llmGateway has adopted the full copium test paradigm (process isolation, CanonicalConfig, gatekeeper infrastructure, pre-commit hooks, CI split) and the PostgreSQL testing infrastructure is built (test-database Docker service, `--run-postgres` CLI flag, `@pytest.mark.postgres` marker). However, several gaps remain: Phase H2 (metric test relocation) was deferred, the Makefile lacks standalone gatekeeper/boundary targets, the `BANNED_OTHER_REGEX` array is missing 2 of 4 blueprint patterns, and — most critically — there is no container lifecycle script to manage PostgreSQL test runs. Before any real-DB integration tests can be written (Phase 6 Blocks 2-7), the foundation must be completed: fix remaining gaps and create the `run-postgres-tests.sh` script that mirrors copium's always-fresh container lifecycle.

## What Changes

- **Phase H2 completion:** Move `test_keeper_metrics.py` from `tests/unit/services/` to `tests/unit/metrics/`, relocate the shared `mock_run_keeper_dependencies` fixture to `tests/unit/conftest.py` to preserve discovery across both subtrees.
- **Makefile standalone targets:** Add `test-gatekeeper` (root-level gatekeeper tests only) and `test-boundary` (single-file boundary compliance fast check) targets matching copium conventions.
- **BANNED_OTHER_REGEX:** Add 2 missing blueprint patterns: `DatabaseConfig\(.*password=...` (non-canonical DB passwords) and `httpcore.*version.*` (version != 1.0.9 enforcement).
- **EXCLUDE_FILES:** Pre-register `test_postgres_policy.py` for the upcoming policy enforcement gatekeeper (Block 6).
- **Container lifecycle script:** Create `scripts/run-postgres-tests.sh` — a production-grade bash script that detects podman/docker, starts a fresh `test-database` container with `--wait`, runs all `@pytest.mark.postgres` tests in isolated groups, and always tears down with `down -v`. Pattern is directly ported from copium's 95-line equivalent, adapted for llmGateway's single-package architecture and asyncpg driver.
- **Makefile `test-postgres` target:** Replace the inline `pytest ... || true` with delegation to `bash scripts/run-postgres-tests.sh`.
- **Test directory scaffold:** Create `tests/integration/db/` directory with `__init__.py` for upcoming integration tests (Blocks 2-5).

## Capabilities

### New Capabilities
- `postgres-test-runner`: Container lifecycle script (`scripts/run-postgres-tests.sh`) that manages Docker/Podman-based PostgreSQL test runs — engine detection (podman-first), always-fresh container lifecycle (down -v → up --wait → test groups → down -v), exit code 5 handling (no tests = graceful skip), accumulated failure reporting. Mirrors copium's `scripts/run-postgres-tests.sh`.
- `test-infra-polish`: Completion of deferred Phase H2 (metrics test relocation + fixture migration), addition of standalone Makefile targets (`test-gatekeeper`, `test-boundary`), and creation of the `tests/integration/db/` directory scaffold for future integration tests.

### Modified Capabilities
- `gatekeeper-hardcode-checker`: Adding 2 missing `BANNED_OTHER_REGEX` patterns (non-canonical DB password regex, httpcore version enforcement regex) per blueprint sections 4.7/4.9. Adding `test_postgres_policy.py` to EXCLUDE_FILES for the upcoming policy enforcement gatekeeper.

## Impact

- `scripts/run-postgres-tests.sh` — **NEW** (~90 lines). Container lifecycle script ported from copium.
- `Makefile` — modified (~+10 lines). New `test-gatekeeper` and `test-boundary` targets; `test-postgres` rewritten to delegate to script.
- `scripts/check-test-hardcodes.sh` — modified (+2 lines in BANNED_OTHER_REGEX, +1 in EXCLUDE_FILES).
- `tests/unit/services/test_keeper_metrics.py` → `tests/unit/metrics/test_keeper_metrics.py` — relocated.
- `tests/unit/services/conftest.py` — modified (−60 lines). `mock_run_keeper_dependencies` fixture moved out.
- `tests/unit/conftest.py` — modified (+60 lines). Now hosts `mock_run_keeper_dependencies`.
- `tests/integration/db/` — **NEW** directory with `__init__.py`. Scaffold for Blocks 2-5.
- No production code changes. Pure test infrastructure and tooling.
