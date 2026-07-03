## Context

After Phase 1, the llmGateway test suite is stable — async event loop hangs are fixed, a global per-test timeout prevents indefinite stalls, all pytest markers are registered, and the environment variable chain is complete. However, there is no build orchestration: developers run `poetry run pytest` which dumps all 1501 tests into a single process with a single asyncio event loop. This causes two problems:

1. **No process isolation**: Cross-contamination between test groups — a test that patches `os.environ` or monkeypatches a module can leak state into unrelated tests. Each test group should get a fresh process with a fresh event loop.
2. **No developer workflow**: No standard way to run subsets of tests. Developers must memorize long `pytest` invocations with `--ignore` flags and marker filters. A `make test` command provides a uniform interface identical to CI.

The inspiration is copium's Makefile — a mature process-isolation pattern refined over multiple CI iterations. Copium splits tests into 6 groups (G1-G6), each a separate `poetry run pytest` invocation, with `-` prefix for fault tolerance on non-gate groups.

llmGateway is a single-package project (unlike copium's two-package monorepo), so the grouping adapts to the existing `tests/` directory structure: unit tests (core vs config), integration, batching, root-level module tests, and stress tests.

## Goals / Non-Goals

**Goals:**
- Provide a Makefile with 5 targets: `test` (G1-G5, day-to-day), `test-slow` (G6, stress, manual), `test-postgres` (opt-in DB tests), `test-all` (everything), `ci` (lint + typecheck + test)
- Split tests into 6 process-isolated groups, each with a fresh asyncio event loop
- Implement per-group `--timeout` overrides (30s for unit, 60s for stress) and marker filters (`-m "not slow and not postgres"`)
- Add `--run-postgres` CLI hook to `tests/conftest.py` so postgres-marked tests are skipped by default
- Rename `tests/test_batching/` → `tests/batching/` to match the `unit/`, `integration/`, `stress/` naming convention
- Verify that the Phase 1 async event loop fix works end-to-end with the new Makefile G6 (stress) group

**Non-Goals:**
- No CheckerResult / _cached_checker_results / checker_result fixtures (gatekeeper infrastructure — next phase)
- No `scripts/check-test-hardcodes.sh` gatekeeper script
- No CanonicalConfig / `_canonical.py` / `_constants.py` (Phase N)
- No gatekeeper test files (15+ files)
- No `.pre-commit-config.yaml`
- No CI pipeline split (GitHub Actions quality.yml)
- No TESTING*.md documentation
- No `tests/AGENTS.md` update
- No deduplication of `_BASE_ENV` dictionaries
- No metrics test relocation

## Decisions

### D1: 6 test groups, G1-G5 in `make test`, G6 in standalone `make test-slow`

**Rationale:** Stress tests (G6) use real HTTP/2 servers with `asyncio.sleep(30)`, take ~7 minutes, and require `--timeout=60`. Including them in `make test` would make every development cycle 7 minutes longer. Copium uses the same pattern: stress/slow tests are in a separate target (`make test-slow`). The `test-all` target chains both for CI completeness.

**Alternatives considered:**
- *All 6 groups in `make test`*: 7-minute cycle unacceptable for development.
- *No stress group at all*: Stress tests validated the Phase 1 async fix — they must remain runnable.
- *Only G1-G4 in `make test`, G5 separate*: G5 (root-level tests) has only 4 fast tests (< 1s each) — no reason to isolate.

### D2: Assignment of llmGateway test directories to groups

The mapping is:

| Group | Directory | Test count | Timeout | Marker filter | `-` prefix |
|-------|-----------|------------|---------|---------------|------------|
| G1 | `tests/unit/ --ignore=tests/unit/config` | ~100 files | 30s | `not slow and not postgres` | No |
| G2 | `tests/unit/config/` | 24 files | 30s | `not slow and not postgres` | Yes |
| G3 | `tests/integration/ tests/security/ tests/e2e/` | 27 files | 30s | `not slow and not postgres` | Yes |
| G4 | `tests/batching/` | 5 files | 30s | `not slow and not postgres` | Yes |
| G5 | `tests/` (root-level, via 6 `--ignore` flags) | 4 files | 30s | `not slow and not postgres` | Yes |
| G6 | `tests/stress/` | 12 files | 60s | `slow` (only) | N/A (separate target) |

**Rationale for the split:**
- **G2 separate from G1**: Config tests are Pydantic-heavy (24 files), use `patch.dict(os.environ, ...)` extensively, and depend on conftest's `setdefault` fallbacks. Isolating them from core unit tests prevents env var leakage.
- **G3 combined**: Integration + security + e2e total 27 files — small enough for one group, and they share the same timeout/marker profile.
- **G5 inversion pattern**: Rather than listing test files by name, G5 collects `tests/` and excludes all subdirectories via `--ignore`. This is copium's "collect everything, then subtract" pattern. It automatically includes future gatekeeper test files without Makefile changes.
- **G1 no `-` prefix**: G1 is the gate — if core unit tests fail, running subsequent groups is pointless. This matches copium where G1 (simlece) is the only group without `-` in `make test`.

**Alternatives considered:**
- *G2 merged into G1*: Config tests would leak `patch.dict` side effects into core unit tests, potentially causing flaky failures.
- *G3 split into 3 groups*: Each directory is small — process overhead (>0.5s per group) outweighs isolation benefit at current scale.
- *G5 lists specific files instead of inversion*: Would need manual updates every time a gatekeeper test is added. Inversion is self-documenting.

### D3: `--run-postgres` hook in conftest rather than in Makefile conditionals

**Rationale:** The `pytest_addoption` + `pytest_collection_modifyitems` pattern is the standard pytest way to implement opt-in markers. It works regardless of how pytest is invoked (Makefile, IDE, direct CLI). The Makefile delegates to it: `test-postgres` passes `--run-postgres`, all other targets omit it. This keeps the Makefile simple (no conditional shell logic) and the behavior testable without Make.

**Alternatives considered:**
- *Shell conditional in Makefile*: Fragile, Makefile-specific, not testable from IDE.
- *Environmental variable `RUN_POSTGRES=1`*: Works but less discoverable than a CLI flag.
- *No hook — use `-m "not postgres"` everywhere*: Works for exclusion but provides no positive discovery path.

### D4: `test_batching/` → `batching/` rename via `git mv`

**Rationale:** All other test subdirectories use prefix-free names: `unit/`, `integration/`, `e2e/`, `security/`, `stress/`. `test_batching/` is an outlier. Deep exploration confirmed zero imports reference `tests.test_batching` — only `src.*` imports. The only reference to the old path is a comment in `test_callback.py:1`. `git mv` preserves file history.

**Alternatives considered:**
- *Leave as-is*: Inconsistent naming is cosmetic but confusing for new contributors. Costs nothing to fix now.

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|------|------------|------------|
| `--timeout=30` kills a test that legitimately takes >30s in G1-G5 | Low | Unit/integration tests complete in <5s. The only tests known to exceed 30s are stress tests (G6, `--timeout=60`). Phase 1 verified global `timeout=30` with 1501 collected tests — no false positives. |
| `--ignore` flags miss a new directory added between phases | Low | G5's inversion pattern (`tests/` minus known subdirectories) automatically picks up new root-level files. A new subdirectory (e.g., `tests/performance/`) would need a `--ignore` addition in G5 and potentially a new group — this is a one-line Makefile change. |
| `-` prefix hides G2-G5 failures in `make test` output | Medium | The `-` prefix is intentional for fault tolerance (G2 fails doesn't block G3). The `ci` target omits all `-` prefixes — CI catches everything. For local development, developers see per-group output before each group runs, so a failing group is clearly identified. |
| `pytest_addoption` conflicts with existing pytest plugins | Low | Standard pytest hook — no known conflicts with pytest-asyncio, pytest-timeout, or pytest-random-order. |
| `git mv test_batching batching` breaks CI if CI references `tests/test_batching/` explicitly | Low | CI runs `poetry run pytest tests/` (no per-directory references). Deep exploration confirmed no references to `tests/test_batching/` in any config or CI file. |
| `make` not available on developer machine | Low | `make` is universally available on Linux/macOS. Windows developers use WSL or Docker. |
