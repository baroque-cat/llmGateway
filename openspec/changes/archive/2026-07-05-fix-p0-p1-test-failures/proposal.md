## Why

The `make test` suite has 24 real test failures (23 in G3 integration/security/e2e, 1 timeout in G4 batching) plus 7 flaky G5 gatekeeper failures. Additionally, `ruff check` reports 99 lint violations in tests/ — 43 of which are F821 undefined-name errors from the `inject_helpers` anti-pattern in integration conftest. The CI pipeline (`make ci`) is red. Every developer push triggers false-negative gatekeeper failures, and `ruff` output is so noisy that real bugs are hidden. Fixing these systematically restores developer confidence and unblocks all future PRs.

## What Changes

- **P0-A (Source fix):** `gateway_service.py` lifespan — replace direct `factory._pool_health_log_interval_sec` attribute access with `getattr(factory, "_pool_health_log_interval_sec", 0)` and guard with `isinstance(interval, int)`. This makes the lifespan robust against `HttpClientFactory` class mocking in tests. 23 integration/security/e2e tests fixed with a single-line change.
- **P0-B (Test fix):** `test_ic01_while_loop_replaces_for_loop` — mock `asyncio.sleep` to prevent 100-second cumulative delay causing 30s timeout. 1 batching test fixed.
- **P0-C (Test fix):** G5 gatekeeper flaky tests — investigate and fix state leakage between Tier 2 synthetic-violation tests and Tier 1 clean-codebase tests that causes 7 false failures when all 155 G5 tests run together.
- **P1 (Test refactor):** Replace the `inject_helpers` runtime namespace-injection fixture in `tests/integration/conftest.py` with a proper `_helpers.py` module and explicit imports. Resolves 42 F821 ruff errors. Also fix 1 genuine F821 (`RequestDetails` in `test_transparent_error_security.py`).

## Capabilities

### Modified Capabilities
- **`pool-health-logging`**: Gateway lifespan startup now uses `getattr` with fallback when accessing `_pool_health_log_interval_sec`, making the health-log loop initialization robust against `HttpClientFactory` substitution in tests.

### New Capabilities
- **`integration-test-helpers`**: A new `tests/integration/_helpers.py` module providing `make_mock_request` and `create_mock_provider_config` as importable utilities, replacing the `inject_helpers` autouse fixture pattern.

## Impact

- **Source code**: 1 line changed in `src/services/gateway/gateway_service.py` (line 933)
- **Test code**: ~8 files modified — 7 integration/security test files get new imports, 1 batching test gets `asyncio.sleep` mock, 1 security test gets `RequestDetails` import fix, 1 new file `tests/integration/_helpers.py`, `tests/integration/conftest.py` simplified
- **No API changes, no dependency changes, no config changes**
- **No breaking changes** — all test helper function signatures preserved, import paths are additive
