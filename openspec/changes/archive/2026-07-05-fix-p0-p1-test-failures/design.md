## Context

The `make test` pipeline has 24 real test failures plus 7 flaky gatekeeper failures and 99 ruff lint violations. These were discovered during a comprehensive audit (see exploration report in prior context). The root causes span three distinct areas: (1) a recent lifespan code change that broke all mocked `HttpClientFactory` usage in integration/security/e2e tests, (2) a batching test with real `asyncio.sleep` calls exceeding the 30s timeout, (3) gatekeeper G5 tests with state leakage between Tier 2 synthetic-violation tests and Tier 1 clean-codebase tests, and (4) an `inject_helpers` runtime namespace-injection pattern in integration conftest that triggers 42 F821 ruff errors.

The project follows a strict testing paradigm with 6 process-isolation groups (G1–G6), a CanonicalConfig single-source-of-truth for all test values, and a zero-hardcodes gatekeeper enforced by `check-test-hardcodes.sh`.

## Goals / Non-Goals

**Goals:**
- Restore `make test` to all-green (G1–G5: zero failures)
- Eliminate all 99 ruff violations in `tests/`
- Make the gateway lifespan robust against `HttpClientFactory` mocking without requiring every test to know about `_pool_health_log_interval_sec`
- Eliminate the `inject_helpers` anti-pattern in favor of standard Python imports (consistent with `AGENTS.md` absolute-import rule)
- Fix the G5 gatekeeper flaky-test problem at its root (state leakage)

**Non-Goals:**
- Do NOT modify the `_pool_health_log_loop` feature itself — only the lifespan initialization guard
- Do NOT add new dependencies or configuration options
- Do NOT change any public API signatures
- Do NOT change `pyrightconfig.json` or ruff rule selection
- P2 (F841 unused vars, B018, E402) and P3 (SIM stylistic) issues in test files are pre-existing and were originally scoped as follow-ups, but were resolved during Section 7 final verification to satisfy `make lint → 0 violations` (required by CI: `ruff check src/ tests/ main.py` without `|| true`)

## Decisions

### D1: Source fix vs. test fix for P0-A (gateway lifespan)

**Decision:** Fix the source (`gateway_service.py:933`) with `getattr(factory, "_pool_health_log_interval_sec", 0)` followed by `isinstance(interval, int) and interval > 0`.

**Alternatives considered:**
- *Fix all 23 tests individually (add `mock_factory._pool_health_log_interval_sec = 0`)* — Rejected due to ~15 modification points across 7 files. Brittle: any new private attribute on `HttpClientFactory` would re-break all tests.
- *Add `_pool_health_log_interval_sec = 0` to the mock in each test file* — Same brittleness concern, plus it burdens test authors with knowing internal implementation details.
- *Use `hasattr` check* — Rejected: `MagicMock` always passes `hasattr` (returns `True`), so `hasattr(factory, "_pool_health_log_interval_sec")` would still be `True` but the returned value would be a `MagicMock`.

**Rationale:** `getattr` with fallback is a necessary first step, but insufficient alone: `MagicMock` auto-creates attributes for any name, so `getattr(MagicMock(), "_pool_health_log_interval_sec", 0)` returns a new `MagicMock`, NOT `0`. The `isinstance(interval, int)` guard catches this and any future non-integer type. In production, the attribute always exists as a real `int`, so `isinstance` check passes and the health loop starts normally. The targeted module `src/services/gateway/` is in `basic` pyright mode, so no type-safety concern.

### D2: `asyncio.sleep` mock vs. delay reduction for P0-B

**Decision:** Mock `asyncio.sleep` at `src.core.probes.asyncio.sleep` in `test_ic01_while_loop_replaces_for_loop`.

**Alternatives considered:**
- *Reduce `start_batch_delay_sec` to 0 or 0.01* — Rejected: would change what the test validates. The test purposefully uses the default 30s delay to verify controller delay-reduction behavior. Reducing it would weaken the invariant check.
- *Mock at global `asyncio.sleep`* — Rejected: too broad, could side-affect other tests in the same G4 process group.
- *Increase pytest timeout for this test* — Rejected: masks the problem. The test should not actually sleep for 100 seconds.

**Rationale:** Mocking `src.core.probes.asyncio.sleep` is targeted and precise. It preserves the controller logic verification while eliminating I/O wait time. This matches the pattern used elsewhere in the codebase.

### D3: Temp-file cleanup vs. cache ordering for P0-C

**Decision:** Identify the exact Tier 2 synthetic test(s) that leak temp files into Tier 1 scans, then add explicit cleanup in `finally` blocks.

**Alternatives considered:**
- *Add `_cleanup_stale_temp_files` to run before each test (not just session start)* — Rejected: adds overhead to all 155 G5 tests, addresses symptom not cause.
- *Run `_cached_checker_results` with autouse session scope before any tests* — Rejected: changes fixture dependency order, may break other test expectations.
- *Use `tmp_path` auto-cleanup exclusively* — Already done; Tier 2 tests use `tmp_path`. The issue is likely a test that writes files outside `tmp_path` (into `tests/unit/` or similar) and fails to remove them.

**Rationale:** The root cause is most likely a Tier 2 test that writes synthetic `.py` files into the real scan directories (`tests/unit/`, `tests/integration/`, etc.) instead of `tmp_path`-based temporary directories. Investigation will surface the exact culprit; the fix is targeted cleanup.

### D4: `_helpers.py` module vs. `# noqa: F821` for P1

**Decision:** Create `tests/integration/_helpers.py` with the two helper functions, remove the `inject_helpers` fixture, and add explicit imports to all 7 consuming test files.

**Alternatives considered:**
- *Add `# noqa: F821` to every call site (42+ lines)* — Rejected: masks real undefined-name errors. If a typo like `make_mock_requst` appears, it would be silently ignored.
- *Add `per-file-ignores = {"tests/integration/**/*.py" = ["F821"]}` to ruff config* — Rejected: even broader masking. Disables F821 for all integration tests permanently.
- *Import from `conftest.py` directly* — Rejected: semantically wrong. `conftest.py` is a pytest fixture file, not a utility module. The project already has `tests/_canonical.py` and `tests/_constants.py` as importable helper modules — `_helpers.py` follows this convention.

**Rationale:** Explicit imports are standard Python, match the project's absolute-import rule (`AGENTS.md`), and are already used by unit tests (e.g., `tests/unit/services/test_gateway_transparent_routing.py` imports `_make_mock_request` from `tests/unit/services/test_gateway_core.py`). This makes the code statically analyzable and self-documenting.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `getattr` fallback silently disables pool health logging if `HttpClientFactory.__init__` fails to set `_pool_health_log_interval_sec` | Production path ALWAYS sets it (line 43-45 of `http_client_factory.py`). Fallback to 0 is safe — it just skips the health loop, same as if config had `pool_health_log_interval_sec: 0`. |
| G5 investigation may not find the exact leaking test on first attempt | If the source test is unclear, fall back to approach B: add `_cleanup_stale_temp_files` that runs `rm -f tests/unit/tmp*.py tests/integration/tmp*.py tests/tmp*.py` before each Tier 1 test. |
| `_helpers.py` import may cause circular imports | `_helpers.py` only imports from `src.*` and `unittest.mock` — no circular dependency possible. It does not import from any test file. |
| Existing code that mutates `request.module.X` manually | No code does this. The `inject_helpers` fixture is the sole injector. After removal, `request.module.make_mock_request` and `request.module.create_mock_provider_config` will no longer be set — existing explicit imports are the only access path. |
