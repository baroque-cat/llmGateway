# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| `test-infra-foundation` | Session-scoped async fixtures receive session-scoped event loop | Stress test server factory starts without error | Existing: `tests/stress/test_ephemeral_server.py` | (existing tests — verification run) | `verify-stress` |
| `test-infra-foundation` | Session-scoped async fixtures receive session-scoped event loop | Function-scoped async fixtures are unaffected | Existing: `tests/unit/config/test_loader.py` | (existing tests — verification run) | `verify-config` |
| `test-infra-foundation` | Every test has a global per-test timeout of 30 seconds | Test that hangs is killed after 30 seconds | `pyproject.toml` static check | `timeout = 30` key present in `[tool.pytest.ini_options]` | `static-checks` |
| `test-infra-foundation` | Every test has a global per-test timeout of 30 seconds | Test with per-test timeout override uses its own value | `tests/stress/test_production_load.py` | (existing `@pytest.mark.timeout(240)` — verify not overridden) | `verify-stress` |
| `test-infra-foundation` | All pytest markers used by the project are registered | Unknown marker produces an error | `pyproject.toml` static check | `markers` list contains `slow`, `postgres`, `meta` | `static-checks` |
| `test-infra-foundation` | All pytest markers used by the project are registered | Registered markers do not produce warnings | `poetry run pytest --co -q` | (collection-only — no UnknownMarkWarning in stderr) | `verify-all` |
| `test-infra-foundation` | .env.example contains all env vars required by the application | All env vars required by the config loader are present | `.env.example` static check | 17 variables present: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, GATEWAY_HOST, GATEWAY_PORT, GATEWAY_WORKERS, KEEPER_METRICS_PORT, METRICS_ACCESS_TOKEN, METRICS_BACKEND, PROMETHEUS_MULTIPROC_DIR, LLM_PROVIDER_DEFAULT_TOKEN, GEMINI_PROD_TOKEN, DEEPSEEK_TOKEN, ANTHROPIC_TOKEN, QWEN_HOME_TOKEN | `static-checks` |
| `test-infra-foundation` | .env.example contains all env vars required by the application | Metrics subsystem env vars are present | `.env.example` static check | `METRICS_BACKEND=` and `PROMETHEUS_MULTIPROC_DIR=` lines present | `static-checks` |
| `test-infra-foundation` | .env.example contains all env vars required by the application | Provider-specific tokens are present | `.env.example` static check | `GEMINI_PROD_TOKEN=`, `DEEPSEEK_TOKEN=`, `ANTHROPIC_TOKEN=`, `QWEN_HOME_TOKEN=` lines present | `static-checks` |
| `test-infra-foundation` | DB_HOST uses localhost in .env.example and database in .env | Source-mode development works with .env.example defaults | `.env.example` static check | Line contains `DB_HOST=localhost` | `static-checks` |
| `test-infra-foundation` | DB_HOST uses localhost in .env.example and database in .env | Docker Compose gets the correct hostname from .env | `.env` static check | Line contains `DB_HOST=database` | `static-checks` |
| `test-infra-foundation` | DB_HOST uses localhost in .env.example and database in .env | .env is gitignored | `git check-ignore .env` | Command exits 0 (file is ignored) | `static-checks` |
| `test-infra-foundation` | tests/conftest.py provides fallback env vars for all variables in .env.example | Config loader test gets all required env vars from conftest | `poetry run pytest tests/unit/config/test_loader.py -q --timeout=30` | All tests pass (no ValueError for missing vars) | `verify-config` |
| `test-infra-foundation` | tests/conftest.py provides fallback env vars for all variables in .env.example | Newly added env vars are covered by conftest defaults | `tests/conftest.py` static check | `_defaults` dict has 17 entries matching `.env.example` vars | `static-checks` |

## Delegation Groups

### Group: static-checks

**Scope:** `.env.example`, `.env`, `pyproject.toml`, `tests/conftest.py` — file content inspection only

| Test Case | Scenarios | Action |
|---|---|---|
| `pyproject.toml` — timeout key check | 1 | VERIFY — grep `timeout = 30` |
| `pyproject.toml` — markers check | 1 | VERIFY — grep `postgres`, `meta` in markers list |
| `pyproject.toml` — asyncio scope check | 0 (coverage row above is stresstest) | VERIFY — grep `asyncio_default_fixture_loop_scope` |
| `.env.example` — variable count check | 4 | VERIFY — count `=` lines, expect 17 |
| `.env.example` — DB_HOST value check | 1 | VERIFY — grep `DB_HOST=localhost` |
| `.env` — DB_HOST value check | 1 | VERIFY — grep `DB_HOST=database` |
| `.env` — gitignored check | 1 | VERIFY — `git check-ignore .env` |
| `tests/conftest.py` — _defaults dict entries | 1 | VERIFY — count entries, expect 17 |

### Group: verify-stress

**Scope:** `tests/stress/` — existing stress tests, run to confirm no hangs

| Test File | Scenarios | Action |
|---|---|---|
| `tests/stress/test_ephemeral_server.py` | 1 | RUN — `poetry run pytest tests/stress/ -q --timeout=60 -m slow` |
| `tests/stress/test_production_load.py` | 1 | (covered by above — full stress suite) |

### Group: verify-config

**Scope:** `tests/unit/config/` — existing config loader tests, run to confirm no env var errors

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_loader.py` | 1 | RUN — `poetry run pytest tests/unit/config/test_loader.py -q --timeout=30` |

### Group: verify-all

**Scope:** Full test collection — confirm no warnings or errors

| Test Case | Scenarios | Action |
|---|---|---|
| Full collection | 1 | RUN — `poetry run pytest --co -q` (collect-only, no errors) |

## Test Modifications

<!-- No existing test changes needed. This phase only modifies configuration files. -->

| File | Change | Reason |
|---|---|---|
| `tests/conftest.py` | Add 6 new entries to `_defaults` dict | `New requirement: tests/conftest.py provides fallback env vars for all variables in .env.example` |
| (no test files) | — | No test logic changes; existing tests verify correctness via re-run |

## Risks & Edge Cases

- **[Risk] `asyncio_default_fixture_loop_scope` breaks existing function-scoped async fixtures** → Verify by running `test_loader.py` (heavily uses function-scoped async fixtures) and `test_ephemeral_server.py` (the session-scoped fixture). If `test_loader.py` fails after the change, the issue is with the scope configuration.
- **[Risk] `timeout = 30` kills legitimate long-running tests** → After initial verification run, check for any `TimeoutError` failures. If found, add `@pytest.mark.timeout(N)` to the specific test with a higher value. Currently only stress tests are known to exceed 30s.
- **[Risk] `--strict-markers` causes UnknownMarkWarning flood** → Run `pytest --co -q` and grep stderr for `PytestUnknownMarkWarning`. If any appear, either register the marker or remove the decorator.
