## Context

The llmGateway test suite has three root-cause problems that prevent reliable execution:

1. **Session-scoped async fixture without event loop scope**: `tests/stress/conftest.py` declares `@pytest_asyncio.fixture(scope="session") async def http2_server_factory()`. pytest-asyncio in strict mode (the default) creates a function-scoped event loop by default. A session-scoped async fixture attempting to use a function-scoped event loop causes `ScopeMismatchError` or, depending on the pytest-asyncio version, hangs during teardown when the loop is closed while the fixture is still alive.

2. **No per-test timeout**: `pytest-timeout` is installed as a dev dependency but never configured. Without a global `timeout` setting, any test that hangs (e.g., stress tests with `asyncio.sleep(30)`, waiting on a TCP connection that never completes) will hang indefinitely. Some stress tests have per-test `@pytest.mark.timeout(N)` decorators, but the majority do not.

3. **Incomplete `.env.example`**: The file is missing 7 variables required by the application runtime (`LLM_PROVIDER_DEFAULT_TOKEN` is injected by `defaults.py`, provider tokens are referenced by `example_full_config.yaml`, `METRICS_BACKEND`/`PROMETHEUS_MULTIPROC_DIR` are read by `src/metrics/__init__.py` bypassing the config system entirely). Additionally, `DB_HOST=database` is a Docker-only hostname — source-mode development (`poetry run python main.py`) requires `localhost`.

The current `tests/conftest.py` works around these gaps with `os.environ.setdefault()` using test-specific synthetic values, but this is a fragile implicit dependency — test files that define their own `_BASE_ENV` dicts only work because conftest provides fallbacks.

## Goals / Non-Goals

**Goals:**
- Fix the event loop scope mismatch so session-scoped async fixtures work correctly
- Add a global per-test timeout so no test can hang indefinitely
- Register all markers (`postgres`, `meta`) that will be used in later phases
- Add `pytest-random-order` for future flaky-test detection
- Complete `.env.example` with all 17 required variables
- Create `.env` (gitignored) as a Docker-ready copy of `.env.example`
- Align `tests/conftest.py` `setdefault` dict with the new `.env.example` variables

**Non-Goals:**
- No Makefile (Phase B)
- No CanonicalConfig frozen dataclass (Phase N)
- No gatekeeper script or pre-commit hook (Phases I, K)
- No test directory renames (Phase E)
- No deduplication of autouse fixtures (Phase H)

## Decisions

### D1: Set ONLY `asyncio_default_fixture_loop_scope`, NOT `asyncio_default_test_loop_scope`

**Rationale:** The stress test conftest uses `scope="session"` for `http2_server_factory`. Setting `asyncio_default_fixture_loop_scope = "session"` gives session-scoped async fixtures a session-scoped event loop — exactly what they need. Leaving `asyncio_default_test_loop_scope` unset preserves the default function-scoped event loop for test functions, preventing accidental state leakage between tests.

**Alternatives considered:**
- *Set both to "session"*: Would make all test functions share one event loop — could introduce flaky order-dependent failures.
- *Change stress fixture to function scope*: Would create/destroy HTTP/2 servers for every test — unacceptable overhead (12 stress tests × server startup/teardown).
- *Use `pytest-asyncio` legacy mode (`asyncio_mode = "auto"`)*: Deprecated, not recommended for new code.

### D2: Global `timeout = 30` rather than per-directory

**Rationale:** A single `timeout` in `[tool.pytest.ini_options]` applies to every test automatically. Individual stress tests with `@pytest.mark.timeout(120)` or `@pytest.mark.timeout(240)` override the global value (per-test marker takes priority). This gives us a safety net for ALL tests without extra configuration.

**Alternatives considered:**
- *Per-Makefile-group timeout flags*: Would require the Makefile to exist first (Phase B). Global timeout works immediately.
- *Higher timeout (60s)*: Too generous — most unit tests complete in < 1s. 30s catches hangs without killing legitimate long tests (which use per-test overrides).

### D3: `DB_HOST=localhost` in `.env.example`, `DB_HOST=database` in `.env`

**Rationale:** Copium uses this exact pattern: the committed template uses `localhost` for source-mode development, the gitignored `.env` overrides to `database` for Docker. This makes the default experience work for `poetry run python main.py` while `docker-compose up` gets the correct Docker hostname automatically (Docker Compose reads `.env` from the project directory).

### D4: Keep `setdefault` in conftest for Phase 1, don't refactor to CanonicalConfig yet

**Rationale:** Phase 1 is about critical fixes that unblock test execution. CanonicalConfig (Phase N) is a larger refactoring that introduces a new module and changes the conftest architecture. Adding only the 6 missing `setdefault` entries maintains backward compatibility with zero risk to existing tests.

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|---|---|---|
| `asyncio_default_fixture_loop_scope` breaks existing function-scoped async fixtures | Low | Only `asyncio_default_fixture_loop_scope` is set. Function-scoped fixtures (the vast majority) use `asyncio_default_test_loop_scope` which stays at default (function). |
| `timeout = 30` kills legitimate long-running tests | Low-Medium | Stress tests already have per-test `@pytest.mark.timeout(N)`. If any other test legitimately takes >30s, it likely indicates a real problem (hanging connection, deadlock). Can add per-test overrides if needed. |
| `--strict-markers` causes `PytestUnknownMarkWarning` for markers used in tests but not registered | Low | Only markers actually used are `slow` (registered) and `asyncio` (from pytest-asyncio plugin). The AGENTS.md mentions `unit`/`integration`/`e2e` but NO test file actually uses them. |
| Adding 7 new env vars to `.env.example` without updating all test `_BASE_ENV` dicts | Low | Phase 1 adds the missing vars to `tests/conftest.py` `setdefault`. Individual test files that use `patch.dict(os.environ, ...)` without `clear=True` will still get fallbacks from conftest. Full CanonicalConfig refactor (Phase N) will consolidate all duplicated dicts. |
| Someone copies the new `.env.example` (with `localhost`) directly to `.env` for Docker | Low | The `.env.example` comment explicitly says "change to 'database' in .env for Docker". Docker Compose would fail to connect, which is loud and obvious. |
