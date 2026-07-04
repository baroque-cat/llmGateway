## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `test-ref`
- [x] 1.2 Run `make test` to verify the full test suite passes before making changes
- [x] 1.3 Run `bash scripts/check-test-hardcodes.sh all` to capture baseline gatekeeper state

## 2. Implementation — BLOCK 0: Fix Remaining Gaps

### 2A. Phase H2: Relocate test_keeper_metrics.py

- [x] 2A.1 Move `mock_run_keeper_dependencies` fixture from `tests/unit/services/conftest.py` to `tests/unit/conftest.py`. Preserve all 13 patches (AsyncIOScheduler, load_config, ConfigAccessor, setup_logging, _setup_directories, database.init_db_pool, database.close_db_pool, DatabaseManager, HttpClientFactory, run_sync_cycle, get_all_probes, get_all_syncers, KeyInventoryExporter). Add imports: `from collections.abc import Generator`, `from unittest.mock import AsyncMock, MagicMock, patch`, `import pytest`, `from types import SimpleNamespace`.
- [x] 2A.2 Remove `mock_run_keeper_dependencies` fixture from `tests/unit/services/conftest.py` (lines ~16-121). Remove unused imports if any.
- [x] 2A.3 Move `tests/unit/services/test_keeper_metrics.py` to `tests/unit/metrics/test_keeper_metrics.py` (git mv). No import changes needed — all imports use absolute `src.*` paths.
- [x] 2A.4 Verify: `poetry run pytest tests/unit/services/test_keeper.py tests/unit/services/test_keeper_export_jobs.py tests/unit/metrics/test_keeper_metrics.py -v` — all must pass.

### 2B. Makefile: standalone targets

- [x] 2B.1 Add `test-gatekeeper` target to `Makefile` after line 31 (G5 step): `poetry run pytest tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching -q --timeout=30 -m "not slow and not postgres"`
- [x] 2B.2 Add `test-boundary` target to `Makefile`: `poetry run pytest tests/test_boundary_compliance.py -q --timeout=30`
- [x] 2B.3 Update `.PHONY` line 1 to include: `test-gatekeeper test-boundary`
- [x] 2B.4 Verify `make test-gatekeeper` runs and passes (G5 tests)

### 2C. BANNED_OTHER_REGEX: add 2 missing patterns

- [x] 2C.1 Add to `scripts/check-test-hardcodes.sh` `BANNED_OTHER_REGEX` array (after line 89): `$'DatabaseConfig\\(.*password="(?!test_password)"'` and `$'httpcore[^.]*version.*[^1][^.]*[^0][^.]*[^9]'`
- [x] 2C.2 Verify: `bash scripts/check-test-hardcodes.sh all` — must exit 0 with new patterns (no false positives on existing codebase)

### 2D. EXCLUDE_FILES: pre-register test_postgres_policy.py

- [x] 2D.1 Add `"test_postgres_policy.py"` to EXCLUDE_FILES in `scripts/check-test-hardcodes.sh` (after line 128, in the Phase 5 block)

### 2E. tests/integration/db/ scaffold

- [x] 2E.1 Create directory: `mkdir -p tests/integration/db`
- [x] 2E.2 Create empty `tests/integration/db/__init__.py`

## 3. Implementation — BLOCK 1: Container Lifecycle Script

### 3A. Create scripts/run-postgres-tests.sh

- [x] 3A.1 Create `scripts/run-postgres-tests.sh` with shebang `#!/usr/bin/env bash` and `set -euo pipefail`. Include:
  - Color constants (RED, GREEN, YELLOW, NC)
  - Path resolution: `SCRIPT_DIR` → `PROJECT_DIR` (repo root)
  - Engine detection: `podman compose` first, then `docker compose` (with `command -v` + `info` checks). Exit 0 with yellow message if neither found.
  - `run_group()` function: `set +e` before pytest, captures `$?`, `set -e` after. Exit 5 → yellow "No postgres tests" (no fail). Exit != 0 and != 5 → red "FAILED" (sets `EXIT_CODE=1`).
  - Pre-teardown: `$COMPOSE_CMD down -v 2>/dev/null || true`
  - Fresh start: `$COMPOSE_CMD up -d --wait test-database`
  - `EXIT_CODE=0`
  - Test groups (all via `run_group`): `schema` (`tests/integration/db/`), `repositories` (`tests/integration/db/` — same dir, separate group for future separation), `manager` (`tests/integration/db/`), `gatekeeper` (inversion: `tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching`)
  - Post-teardown: `$COMPOSE_CMD down -v` (no error suppression)
  - Final: `exit $EXIT_CODE`
- [x] 3A.2 Make script executable: `chmod +x scripts/run-postgres-tests.sh`
- [x] 3A.3 Verify: `bash -n scripts/run-postgres-tests.sh` (syntax check, no errors)
- [x] 3A.4 Verify: `shellcheck scripts/run-postgres-tests.sh` (if available) — must exit 0

### 3B. Update Makefile test-postgres target

- [x] 3B.1 Replace line 39-40 in `Makefile` (current `test-postgres: poetry run pytest -v --run-postgres -m "postgres" || true`) with: `test-postgres: bash scripts/run-postgres-tests.sh`
- [x] 3B.2 Verify: `make test-postgres` exits 0 gracefully (no container engine → skip message, or container engine → starts test-database, collects 0 tests with exit 5 per group)

## 4. Testing

- [x] 4.1 Read `test-plan.md` Delegation Groups section
- [x] 4.2 Delegate group `postgres-runner-gatekeeper` to @Mr.Tester (scope: `tests/test_postgres_runner.py`)
- [x] 4.3 Delegate group `infra-polish` to @Mr.Tester (scope: `tests/test_test_infra_polish.py`)
- [x] 4.4 Delegate group `gatekeeper-patterns` to @Mr.Tester (scope: `tests/test_hardcode_checker_patterns.py` — MODIFY, add 3 tests)
- [x] 4.5 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 4.6 Re-delegate any groups affected by source fixes
- [x] 4.7 Verify all groups pass and coverage matches `test-plan.md`

## 5. Integration & Verification

- [x] 5.1 Run `bash scripts/check-test-hardcodes.sh all` — must exit 0 with new BANNED_OTHER_REGEX patterns and EXCLUDE_FILES entry
- [x] 5.2 Run `make test` — G5 must collect all new gatekeeper test files, all must pass. No regressions vs baseline.
- [x] 5.3 Run `make lint && make typecheck` — no new errors on changed files
- [x] 5.4 Run `shellcheck scripts/run-postgres-tests.sh` — must exit 0
- [x] 5.5 Verify `make test-gatekeeper` runs and passes
- [x] 5.6 Verify `make test-boundary` runs and passes
- [x] 5.7 Verify `tests/test_hardcode_checker_patterns.py` (modified) covers the 2 new BANNED_OTHER_REGEX patterns and the EXCLUDE_FILES entry
