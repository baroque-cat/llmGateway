## Context

After Phase 5, llmGateway's PostgreSQL testing infrastructure is fully built (test-database Docker service on port 5433, `--run-postgres` CLI flag, `@pytest.mark.postgres` marker, `make test-postgres` target) but no container lifecycle script exists and several deferred Phase H2 items remain unfinished. The copium project serves as the reference implementation — its `scripts/run-postgres-tests.sh` (95 lines) provides an always-fresh container lifecycle (down -v → up --wait → test groups → down -v) that is enforced by gatekeeper policy tests.

Two remaining gaps from `problem_tests.md` Phase H/I:
- Phase H2: `test_keeper_metrics.py` was never relocated from `tests/unit/services/` to `tests/unit/metrics/` because its `mock_run_keeper_dependencies` fixture lives in `tests/unit/services/conftest.py` (directory-scoped fixture discovery would break).
- Phase I: 2 of 4 `BANNED_OTHER_REGEX` patterns are missing from the gatekeeper script.

Additionally, llmGateway's Makefile embeds the gatekeeper inversion pattern in G5 but lacks standalone `test-gatekeeper` and `test-boundary` targets that copium provides for fast development workflows.

## Goals / Non-Goals

**Goals:**
- Complete Phase H2: relocate `test_keeper_metrics.py` to `tests/unit/metrics/` by moving the shared `mock_run_keeper_dependencies` fixture to `tests/unit/conftest.py` (which already re-exports the metrics isolation fixture and covers both subtrees).
- Add `test-gatekeeper` and `test-boundary` standalone Makefile targets matching copium conventions.
- Add 2 missing `BANNED_OTHER_REGEX` patterns to the gatekeeper script.
- Pre-register `test_postgres_policy.py` in EXCLUDE_FILES for the upcoming Block 6 policy enforcement gatekeeper.
- Create `scripts/run-postgres-tests.sh` — a production-grade container lifecycle script ported from copium's equivalent, adapted for llmGateway's single-package architecture and asyncpg driver.
- Create `tests/integration/db/` directory scaffold for future integration tests (Blocks 2-5).

**Non-Goals:**
- No actual PostgreSQL integration tests written (those are Blocks 2-5, out of scope for this change).
- No CI workflow changes (postgres CI job is Block 7).
- No `test_postgres_policy.py` gatekeeper yet (that is Block 6).
- No changes to `docker-compose.yml` (test-database service already exists from Phase M).
- No changes to `src/db/database.py` or any production code.
- No changes to `tests/conftest.py` root conftest (`--run-postgres` hook already exists).

## Decisions

### D1: `mock_run_keeper_dependencies` moves to `tests/unit/conftest.py`, not `tests/unit/services/conftest.py` or a duplicate

**Rationale:** The fixture is used by tests in both `tests/unit/services/` (test_keeper.py, test_keeper_export_jobs.py) and, after relocation, `tests/unit/metrics/` (test_keeper_metrics.py). Placing it in `tests/unit/conftest.py` makes it available to both subtrees via pytest's conftest discovery hierarchy. This is the same pattern already used for `_isolate_metrics_collector` re-export (D1 from Phase 5).

**Alternatives considered:**
- *Duplicate the fixture into `tests/unit/metrics/conftest.py`:* Would create maintenance burden (two copies of the same 60-line fixture). Violates the DRY principle that Phase H was specifically designed to fix.
- *Leave the file in `tests/unit/services/`:* The file tests Keeper's use of metrics, and Keeper IS a service — the current location is semantically correct. However, the blueprint (Phase H) explicitly prescribes the move, and having all metrics-related tests in one directory improves discoverability.

### D2: `run-postgres-tests.sh` uses podman-first engine detection, identical to copium

**Rationale:** Copium's script checks podman first because it's the recommended container runtime for development environments. The pattern (`command -v podman && podman info` then `command -v docker && docker info`) handles both engines gracefully. If neither is available, the script exits 0 (skip, not failure) — this allows CI environments without a container runtime to still pass.

**Alternatives considered:**
- *docker-first detection:* Would break for users who have both installed but prefer podman. Copium's podman-first approach is the industry convention for development tooling.
- *Require one specific engine:* Unnecessarily restrictive. Docker is standard on CI; podman is preferred on development machines.

### D3: `run-postgres-tests.sh` targets the `test-database` service, not `database`

**Rationale:** llmGateway has two PostgreSQL services in `docker-compose.yml`: `database` (production, port not exposed, credentials from env vars) and `test-database` (port 5433, hardcoded test-safe credentials `test_user`/`test_password`/`test_db`). The script MUST target `test-database` to avoid accidentally starting the production database service and to ensure test credentials are used.

### D4: `--wait` flag replaces `sleep` for container readiness

**Rationale:** Copium's `docker compose up -d --wait database` blocks until the container healthcheck passes. This is more reliable than `sleep N` which introduces flaky timing dependencies (containers may start faster or slower depending on hardware). The policy enforcement gatekeeper (Block 6) will verify that the script uses `--wait` and contains no `sleep` calls.

### D5: `run_group` function handles exit code 5 (no tests collected)

**Rationale:** When `@pytest.mark.postgres` tests are first being written, some groups may have zero tests. pytest returns exit code 5 for "no tests collected" — this should be treated as a non-failure (yellow informational message, `EXIT_CODE` unchanged). This is the same pattern used in copium's script.

### D6: Pre-teardown `down -v` suppresses errors; post-teardown `down -v` does not

**Rationale:** The pre-teardown removes any stale container from a previous crashed run — if no container exists, compose prints errors to stderr (suppressed with `2>/dev/null || true`). The post-teardown runs after tests complete — if it fails, something went wrong and the error should be visible (no suppression, `set -e` active). This mirrors copium's exact error-handling pattern.

### D7: `BANNED_OTHER_REGEX` additions use `$'...'` ANSI-C quoting for regex special characters

**Rationale:** The two new patterns contain regex special characters (`(`, `)`, `[`, `]`, `^`, `.`, `*`). Bash's `$'...'` quoting correctly handles these without escaping confusion. This is consistent with existing patterns in the same array.

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|------|------------|------------|
| Moving `mock_run_keeper_dependencies` breaks other tests in `tests/unit/services/` | Low | The fixture moves to a conftest one level higher in the hierarchy — pytest's discovery will still find it. All tests that import it continue to work. Verify with `pytest tests/unit/services/ tests/unit/metrics/test_keeper_metrics.py -v` after move. |
| `run-postgres-tests.sh` fails on systems without `docker compose` v2 plugin | Low | The script detects both podman and docker with `command -v` and `info` checks. If neither is available, it exits 0 gracefully. The error message clearly states the requirement. |
| `--wait` flag not supported in older docker-compose versions | Low | Docker Compose v2 has been the default since 2022. The script checks `docker info` which fails on v1. If `--wait` is unsupported, the `up` command would fail immediately (visible error), not silently hang. |
| `test-database` port 5433 conflicts with another local PostgreSQL instance | Medium | Port 5433 is intentionally non-standard to avoid conflicts. If occupied, the `up` command fails visibly. No automatic port selection — user must free the port. |
| New `BANNED_OTHER_REGEX` patterns produce false positives | Low | The `DatabaseConfig` regex uses a negative lookahead (`(?!test_password)`) to allow the canonical test password. The `httpcore` regex is character-class-based to avoid false positives on version strings that happen to contain "1.0.9" as a substring. Both patterns are validated against existing codebase before being committed. |
