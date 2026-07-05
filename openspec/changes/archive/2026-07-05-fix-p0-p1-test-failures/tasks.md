## 1. Git & Environment

- [x] 1.1 Create a new git branch: `git checkout -b test-ref`
- [x] 1.2 Record baseline: run `make test 2>&1 | tee /tmp/baseline_test.log` and verify 24 failed + 7 gatekeeper flaky
- [x] 1.3 Run `poetry run ruff check tests/ --output-format=concise | wc -l` and verify 99 violations baseline

## 2. P0-A: Gateway lifespan fix (`gateway_service.py`)

- [x] 2.1 In `src/services/gateway/gateway_service.py` line 933, replace:
  ```python
  interval = factory._pool_health_log_interval_sec
  if interval > 0:
  ```
  with:
  ```python
  interval = getattr(factory, "_pool_health_log_interval_sec", 0)
  if isinstance(interval, int) and interval > 0:
  ```
- [x] 2.2 Verify fix: `poetry run pytest tests/integration/ tests/security/ tests/e2e/ -q --timeout=30 -m "not slow and not postgres"` → 0 failed (was 23)
- [x] 2.3 Run `make test` and verify G3 returns to all-green in the report

## 3. P0-B: Batching test timeout fix

- [x] 3.1 In `tests/batching/test_probe_adaptive_integration.py::test_ic01_while_loop_replaces_for_loop`, wrap line 133 (`await probe._process_provider_batch(...)`) with:
  ```python
  with patch("src.core.probes.asyncio.sleep", new_callable=AsyncMock):
      await probe._process_provider_batch("test_provider", resources)
  ```
  (Import `AsyncMock` and `patch` from `unittest.mock` if not already present — they are already imported at line 15.)
- [x] 3.2 Verify fix: `poetry run pytest tests/batching/test_probe_adaptive_integration.py::test_ic01_while_loop_replaces_for_loop -v --timeout=30` → PASSED in <5 seconds
- [x] 3.3 Run full G4: `poetry run pytest tests/batching/ -q --timeout=30 -m "not slow and not postgres"` → 0 failed

## 4. P0-C: G5 gatekeeper flaky test fix

- [x] 4.1 Investigate and fix state leakage in `tests/test_hardcode_checker_core.py`: wrap all 13 Tier 2 synthetic tests in `try/finally` with `Path.unlink(missing_ok=True)` cleanup of the temp `.py` file each test creates. Find the temp file path variable used in each test's `_make_temp_py()` call and add `try: ... finally: temp_path.unlink(missing_ok=True)`.
- [x] 4.2 Apply same `try/finally` pattern to `tests/test_hardcode_checker_modes.py` — tests `test_canonical_mode_enforces_strict_zero_hardcodes` and `test_all_mode_runs_all_three_sequentially`.
- [x] 4.3 Apply same `try/finally` pattern to `tests/test_hardcode_checker_regression.py` — tests `test_all_mode_passes_on_clean_codebase` and `test_canonical_mode_passes` (if they create temp files).
- [x] 4.4 Apply same `try/finally` pattern to `tests/test_conftest_checker_cache.py` — tests that write temp files: `test_cleanup_stale_temp_files_removes_leftovers`, `test_compute_checker_hash_reflects_file_changes`, `test_hash_covers_scanned_test_files`, `test_hash_excludes_pycache`, `test_hash_excludes_init_py`.
- [x] 4.5 Verify fix: run G5 3 consecutive times to confirm no flaky failures:
  ```bash
  for i in 1 2 3; do
    echo "=== Run $i ==="
    poetry run pytest tests/test_*.py -q --timeout=30 -m "not slow and not postgres" --ignore=tests/ --ignore-glob='tests/*/' 2>&1 | tail -3
  done
  ```
- [x] 4.6 If flaky failures persist after `try/finally`, implement fallback approach B (design.md): add a function-scoped autouse fixture in `tests/conftest.py` that removes `_gate_synth_*.py` and `tmp*.py` from `tests/unit/`, `tests/integration/`, and `tests/` root before each Tier 1 test.

## 5. P1: Remove `inject_helpers` anti-pattern

- [x] 5.1 Create `tests/integration/_helpers.py`: extract `make_mock_request` and `create_mock_provider_config` functions from `tests/integration/conftest.py` (lines 24–85), copying signatures, default arguments, and return types exactly. Imports needed: `AsyncMock`, `MagicMock` from `unittest.mock`; `Request` from `fastapi`; `GatewayPolicyConfig`, `ModelInfo`, `ProviderConfig`, `RetryOnErrorConfig`, `RetryPolicyConfig` from `src.config.schemas`; `DebugMode`, `StreamingMode` from `src.core.constants`.
- [x] 5.2 Modify `tests/integration/conftest.py`: remove `inject_helpers` fixture (lines 88–92). Remove `make_mock_request` and `create_mock_provider_config` definitions (lines 24–85). Remove now-unused imports. Keep `_isolate_metrics_collector` fixture intact.
- [x] 5.3 Add `from tests.integration._helpers import make_mock_request` to each integration test file that uses it:
  - `tests/integration/test_gateway_refactor.py`
  - `tests/integration/test_error_parsing_catch_all.py`
  - `tests/integration/test_gateway_retry_synergy.py`
  - `tests/integration/test_stream_closed_bug.py`
  - `tests/integration/test_unified_error_parsing.py`
- [x] 5.4 Add `from tests.integration._helpers import create_mock_provider_config` to:
  - `tests/integration/test_gateway_dispatcher_routing.py`
  - `tests/integration/test_gateway_full_duplex_streaming.py`
- [x] 5.5 Fix the `RequestDetails` F821 in `tests/security/test_transparent_error_security.py`:
  - Add `RequestDetails` to the module-level import: `from src.core.models import CheckResult, RequestDetails`
  - Remove the local import `from src.core.models import RequestDetails` inside the method body (line 588)
  - Replace the string forward-reference `"RequestDetails"` (line 587) with direct `RequestDetails`
- [x] 5.6 Verify all F821 errors resolved: `poetry run ruff check tests/ --select F821` → 0 violations
- [x] 5.7 Verify integration tests still pass: `poetry run pytest tests/integration/ -q --timeout=30 -m "not slow and not postgres"` → all passing

## 6. Testing — Delegate to @Mr.Tester

**CRITICAL INSTRUCTIONS FOR THE PROGRAMMER AGENT:** When delegating test work to @Mr.Tester subagents, you MUST pass ALL of the following documentation files as context alongside each sub-task. This ensures the tester follows project conventions:
- `AGENTS.md` — project conventions, import style, naming
- `TESTING.md` — Golden Rule, process-isolation groups, directory structure
- `TESTING-RUN.md` — Makefile targets, marker conventions, timeout policy
- `TESTING-GUIDE.md` — CanonicalConfig usage, boundary annotations, anti-patterns
- `TESTING-GATEKEEPER.md` — gatekeeper architecture, banned-pattern arrays

The tester MUST also read: `openspec/changes/fix-p0-p1-test-failures/design.md`, `test-plan.md`, and relevant spec files from `specs/`.

- [x] 6.1 Read `test-plan.md` Delegation Groups section to understand all groups and their scopes
- [x] 6.2 Delegate group `gateway-pool-health` to @Mr.Tester (scope: `tests/unit/services/test_gateway_core.py`). Task: Write 3 NEW tests and update 3 existing tests per test-plan.md Coverage Map rows S1–S4, S6, S7. The `TestPoolHealthLogLoop` class already exists in this file; add the new tests to it and modify existing ones. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.3 Delegate group `config-pool-health-default` to @Mr.Tester (scope: `tests/unit/config/test_http_client_config.py`). Task: Update `test_ut_hc25_default_value` docstring per coverage row S5. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.4 Delegate group `batching-async-mock` to @Mr.Tester (scope: `tests/batching/test_probe_adaptive_integration.py`). Task: Verify the `asyncio.sleep` mock added in step 3.1 works correctly and the test assertions at lines 136–152 still pass. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.5 Delegate group `security-request-details` to @Mr.Tester (scope: `tests/security/test_transparent_error_security.py`). Task: Verify the `RequestDetails` import fix from step 5.5 is correct and no new ruff violations are introduced. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.6 Delegate group `integration-helpers` to @Mr.Tester (scope: `tests/integration/`). Task: Create `tests/integration/_helpers.py` and `tests/integration/test_helpers_import.py` (5 NEW tests per coverage rows S8, S9, S11, S12, S13). Verify that after removing `inject_helpers` fixture and adding explicit imports to 7 consuming test files, all integration tests pass. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.7 Delegate group `gatekeeper-state-leakage` to @Mr.Tester (scope: 4 G5 root-level test files). Task: Verify the `try/finally` cleanup added in steps 4.1–4.4 resolves the flaky test problem. Run all G5 tests 3 consecutive times and confirm zero flaky failures. If flaky failures persist, implement fallback approach B. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.8 Delegate group `gatekeeper-helpers-migration` to @Mr.Tester (scope: `tests/test_integration_helpers_migration.py`). Task: Create NEW test file with 2 tests per coverage row S10 and the migration verification test. Pass `AGENTS.md TESTING.md TESTING-RUN.md TESTING-GUIDE.md TESTING-GATEKEEPER.md` as context.
- [x] 6.9 Review all @Mr.Tester reports. Fix any source-level bugs discovered.
- [x] 6.10 Re-delegate any groups affected by source fixes.

## 7. Final Verification

- [x] 7.1 Run `make test` — all groups G1–G5 must be green:
  ```
  G1: 885+ passed, 0 failed
  G2: 304+ passed, 0 failed
  G3: 134+ passed, 0 failed (was 23 failed)
  G4: 107 passed, 0 failed (was 1 timeout)
  G5: 157+ passed, 0 failed (was 7 flaky)
  ```
- [x] 7.2 Run `make lint` → 0 violations (was 99)
- [x] 7.3 Run `make typecheck` → 0 errors, 0 warnings (unchanged)
- [x] 7.4 Run `make ci` → all steps pass (ruff + pyright + test)
- [x] 7.5 Run `bash scripts/check-test-hardcodes.sh all` → "All test hardcode checks passed"
