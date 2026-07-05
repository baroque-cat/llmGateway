# QA Strategy & Test Plan

> Change: `fix-p0-p1-test-failures`
> Specs: `pool-health-logging` (MODIFIED + ADDED), `integration-test-helpers` (ADDED)
> Source fix: `src/services/gateway/gateway_service.py:933` — replace direct attribute access `factory._pool_health_log_interval_sec` with `getattr(factory, "_pool_health_log_interval_sec", 0)` and guard with `isinstance(interval, int) and interval > 0`.

## Coverage Map

Every `#### Scenario:` header from both spec files is mapped to a concrete test file, test function name, and delegation group.

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health log line format | `tests/unit/services/test_gateway_core.py` | `test_health_log_includes_per_connection_details` | gateway-pool-health |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging respects configured interval | `tests/unit/services/test_gateway_core.py` | `test_health_logging_respects_interval` | gateway-pool-health |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging disabled when interval is zero | `tests/unit/services/test_gateway_core.py` | `test_health_logging_disabled_when_zero` | gateway-pool-health |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging disabled when interval attribute is inaccessible | `tests/unit/services/test_gateway_core.py` | `test_health_logging_disabled_when_attribute_inaccessible` | gateway-pool-health |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging interval configurable | `tests/unit/config/test_http_client_config.py` | `test_ut_hc25_default_value` | config-pool-health-default |
| pool-health-logging | Gateway lifespan startup is resilient to HttpClientFactory substitution | Real HttpClientFactory starts health loop normally | `tests/unit/services/test_gateway_core.py` | `test_real_factory_starts_health_loop` | gateway-pool-health |
| pool-health-logging | Gateway lifespan startup is resilient to HttpClientFactory substitution | Mocked HttpClientFactory falls back gracefully | `tests/unit/services/test_gateway_core.py` | `test_mocked_factory_falls_back_gracefully` | gateway-pool-health |
| integration-test-helpers | Helpers are importable from a static module | Explicit import resolves statically | `tests/integration/test_helpers_import.py` | `test_make_mock_request_importable_statically` | integration-helpers |
| integration-test-helpers | Helpers are importable from a static module | Import style follows project conventions | `tests/integration/test_helpers_import.py` | `test_helpers_use_absolute_import_syntax` | integration-helpers |
| integration-test-helpers | inject_helpers fixture is removed | No F821 errors after removal | `tests/test_integration_helpers_migration.py` | `test_no_f821_errors_for_helper_names` | gatekeeper-helpers-migration |
| integration-test-helpers | inject_helpers fixture is removed | All integration tests pass after removal | `tests/integration/test_helpers_import.py` | `test_helpers_work_in_integration_context` | integration-helpers |
| integration-test-helpers | Helper functions maintain the same API | make_mock_request signature preserved | `tests/integration/test_helpers_import.py` | `test_make_mock_request_signature_preserved` | integration-helpers |
| integration-test-helpers | Helper functions maintain the same API | create_mock_provider_config signature preserved | `tests/integration/test_helpers_import.py` | `test_create_mock_provider_config_signature_preserved` | integration-helpers |

**Scenario count:** 13 total (7 pool-health-logging + 6 integration-test-helpers).

---

## Delegation Groups

Groups are non-overlapping by file. Each file appears in exactly one group. Groups align with the process-isolation groups (G1–G6) from `TESTING-RUN.md`.

### Group: gateway-pool-health

**Scope:** `tests/unit/services/test_gateway_core.py` (G1)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_core.py` | 6 (S1–S4, S6, S7) | MODIFY + NEW |

**Details:**
- **MODIFY** 3 existing tests in `TestPoolHealthLogLoop`:
  - `test_health_log_includes_per_connection_details` — update docstring to reference spec scenario. No logic change.
  - `test_health_logging_respects_interval` — update docstring. No logic change.
  - `test_health_logging_disabled_when_zero` — remove stale comment about "pre-existing MagicMock > int TypeError" (now fixed). Test still works: `getattr(factory, "_pool_health_log_interval_sec", 0)` returns `0` when attribute is set to `0`.
- **NEW** 3 tests in `TestPoolHealthLogLoop`:
  - `test_health_logging_disabled_when_attribute_inaccessible` — full lifespan test: mock `HttpClientFactory` with bare `MagicMock`, trigger lifespan, assert no `TypeError`, assert `pool_health_task` NOT set. Primary regression test for P0-A.
  - `test_real_factory_starts_health_loop` — real `HttpClientFactory` with `pool_health_log_interval_sec=60`, trigger lifespan, assert health task IS started.
  - `test_mocked_factory_falls_back_gracefully` — `isinstance` check: `getattr(MagicMock(), "_pool_health_log_interval_sec", 0)` returns a `MagicMock`, `isinstance(ret, int)` returns `False`, so `and` short-circuits to `False`.

### Group: config-pool-health-default

**Scope:** `tests/unit/config/test_http_client_config.py` (G2)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_http_client_config.py` | 1 (S5) | MODIFY |

**Details:**
- **MODIFY** `test_ut_hc25_default_value` — update docstring to reference spec scenario. Verify `config.pool_health_log_interval_sec == 60` still passes.

### Group: batching-async-mock

**Scope:** `tests/batching/test_probe_adaptive_integration.py` (G4)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/batching/test_probe_adaptive_integration.py` | 0 (modification only) | MODIFY |

**Details:**
- **MODIFY** `test_ic01_while_loop_replaces_for_loop` — add `with patch("src.core.probes.asyncio.sleep", new=AsyncMock())` around `await probe._process_provider_batch(...)`. Mocking `src.core.probes.asyncio.sleep` is targeted (not global), preserves controller logic verification.
- **MODIFY** `test_ic11_adaptive_batching_absent_uses_default_factory` — same root cause: 30 resources with default 30s `start_batch_delay_sec` causes cumulative ~54s delay exceeding the 30s pytest timeout. Same fix applied (patch `src.core.probes.asyncio.sleep`).

### Group: security-request-details

**Scope:** `tests/security/test_transparent_error_security.py` (G3)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/security/test_transparent_error_security.py` | 0 (modification only) | MODIFY |

**Details:**
- **MODIFY** module-level imports — add `RequestDetails` to `from src.core.models import ...`. Remove local import inside method body. Replace string forward-reference `"RequestDetails"` with direct `RequestDetails`.

### Group: integration-helpers

**Scope:** `tests/integration/` directory (G3)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/integration/_helpers.py` | — | NEW |
| `tests/integration/conftest.py` | — | MODIFY |
| `tests/integration/test_helpers_import.py` | 5 (S8, S9, S11, S12, S13) | NEW |
| `tests/integration/test_gateway_refactor.py` | — | MODIFY |
| `tests/integration/test_gateway_full_duplex_streaming.py` | — | MODIFY |
| `tests/integration/test_stream_closed_bug.py` | — | MODIFY |
| `tests/integration/test_unified_error_parsing.py` | — | MODIFY |
| `tests/integration/test_error_parsing_catch_all.py` | — | MODIFY |
| `tests/integration/test_gateway_dispatcher_routing.py` | — | MODIFY |
| `tests/integration/test_gateway_retry_synergy.py` | — | MODIFY |

**Details:**
- **NEW** `tests/integration/_helpers.py` — extract `make_mock_request` and `create_mock_provider_config` from `tests/integration/conftest.py`. Copy signatures, defaults, return types exactly.
- **MODIFY** `tests/integration/conftest.py` — remove `inject_helpers` fixture (lines 88–92). Remove function definitions (lines 24–85). Remove unused imports. Keep `_isolate_metrics_collector`.
- **NEW** `tests/integration/test_helpers_import.py` — 5 tests verifying importability, absolute import style, integration context, and signature preservation.
- **MODIFY** 7 consuming test files — add explicit `from tests.integration._helpers import ...` at top.

### Group: gatekeeper-state-leakage

**Scope:** 4 root-level G5 test files

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_hardcode_checker_core.py` | — | MODIFY |
| `tests/test_hardcode_checker_modes.py` | — | MODIFY |
| `tests/test_hardcode_checker_regression.py` | — | MODIFY |
| `tests/test_conftest_checker_cache.py` | — | MODIFY |

**Details:**
- **MODIFY** all 4 files — wrap temp-file creating tests in `try/finally` with `Path.unlink(missing_ok=True)` cleanup. If investigation doesn't find exact leaking test, use fallback approach B: add function-scoped fixture that runs `rm -f` on `tmp*.py` and `_gate_synth_*.py` before Tier 1 tests.

### Group: gatekeeper-helpers-migration

**Scope:** `tests/test_integration_helpers_migration.py` (G5)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/test_integration_helpers_migration.py` | 1 (S10) | NEW |

**Details:**
- **NEW** `tests/test_integration_helpers_migration.py` — `test_no_f821_errors_for_helper_names` (subprocess ruff check) + `test_inject_helpers_fixture_removed` (grep conftest.py).

---

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/batching/test_probe_adaptive_integration.py` | Add `patch("src.core.probes.asyncio.sleep", new=AsyncMock())` in `test_ic01` and `test_ic11` | P0-B: cumulative sleep exceeds 30s timeout (100s in test_ic01, ~54s in test_ic11) |
| `tests/security/test_transparent_error_security.py` | Add `RequestDetails` to module-level imports | F821 ruff violation |
| `tests/integration/conftest.py` | Remove `inject_helpers` + function definitions | P1: runtime namespace injection invisible to ruff |
| `tests/integration/test_gateway_refactor.py` | Add `from tests.integration._helpers import make_mock_request` | P1: 26 call sites |
| `tests/integration/test_gateway_full_duplex_streaming.py` | Add `from tests.integration._helpers import create_mock_provider_config` | P1: 2 call sites |
| `tests/integration/test_stream_closed_bug.py` | Add `from tests.integration._helpers import make_mock_request` | P1: 2 call sites |
| `tests/integration/test_unified_error_parsing.py` | Add `from tests.integration._helpers import make_mock_request` | P1: 1 call site |
| `tests/integration/test_error_parsing_catch_all.py` | Add `from tests.integration._helpers import make_mock_request` | P1: 5 call sites |
| `tests/integration/test_gateway_dispatcher_routing.py` | Add `from tests.integration._helpers import create_mock_provider_config` | P1: 4 call sites |
| `tests/integration/test_gateway_retry_synergy.py` | Add `from tests.integration._helpers import make_mock_request` | P1: 2 call sites |
| `tests/test_hardcode_checker_core.py` | Wrap 13 Tier 2 tests in `try/finally` cleanup | P0-C: temp file leakage |
| `tests/test_hardcode_checker_modes.py` | Wrap `test_canonical_mode_enforces` and `test_all_mode_runs` in `try/finally` | P0-C: temp file leakage |
| `tests/test_hardcode_checker_regression.py` | Wrap `test_all_mode_passes` and `test_canonical_mode_passes` (if using temp files) | P0-C: temp file leakage |
| `tests/test_conftest_checker_cache.py` | Wrap 5 temp-file tests in `try/finally` cleanup | P0-C: temp file leakage |
| `tests/unit/services/test_gateway_core.py` | Remove stale comment about MagicMock TypeError; add 3 new tests | P0-A: test coverage for `isinstance` guard |

---

## Risks & Edge Cases

- **[CRITICAL] `MagicMock` auto-attribute behavior bypasses `getattr` fallback** — `getattr(MagicMock(), "_pool_health_log_interval_sec", 0)` returns a `MagicMock`, NOT `0`, because `MagicMock` auto-creates attributes for any name. **Fix: use `isinstance(interval, int) and interval > 0`** instead of plain `interval > 0`. This guards against both `MagicMock` and any future non-integer type. Test `test_mocked_factory_falls_back_gracefully` verifies this.
- **[HIGH] G5 investigation may not find exact leaking test on first attempt** — fall back to approach B: function-scoped cleanup fixture that removes `_gate_synth_*.py`/`tmp*.py` before each Tier 1 test. Verify by running `make test` 5 consecutive times.
- **[MEDIUM] `_helpers.py` import circular dependency** — only imports from `src.*` and `unittest.mock`. Smoke test: `python -c "from tests.integration._helpers import make_mock_request"` in CI.
- **[MEDIUM] Orphaned `request.module.X` references** — `ruff check --select F821` catches statically; runtime `NameError` caught by G3 tests.
- **[LOW] `make_mock_request` `url` parameter accepted but unused** — retained for backward compatibility. Pre-existing issue, not introduced by this change.
