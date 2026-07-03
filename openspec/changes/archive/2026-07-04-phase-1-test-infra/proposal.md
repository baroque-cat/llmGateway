## Why

The llmGateway test suite is in a broken state: tests hang when run as a full suite (not individually), there is no per-test timeout to kill stuck tests, and the environment variable chain is incomplete — `.env.example` is missing 7 required variables, `DB_HOST` uses a Docker-only hostname unsuitable for source-mode development, and `.env` does not exist yet. This Phase 1 establishes the critical pytest configuration fixes and environment variable foundation that make tests actually runnable before any further refactoring.

## What Changes

- **`pyproject.toml`**: Add `asyncio_default_fixture_loop_scope = "session"` (fixes root cause of stress test hangs — session-scoped `http2_server_factory` in `tests/stress/conftest.py` receiving wrong event loop). Add `timeout = 30` global per-test timeout (kills any test stuck >30s). Add `addopts = ["--strict-markers", "--strict-config"]`. Register `postgres` and `meta` markers alongside existing `slow`. **BREAKING**: tests that previously hung silently will now fail with `TimeoutError` after 30 seconds.
- **`pyproject.toml` dev-dependencies**: Add `pytest-random-order (>=1.1.0,<2.0.0)`.
- **`.env.example`**: Add 7 missing variables (`LLM_PROVIDER_DEFAULT_TOKEN`, `GEMINI_PROD_TOKEN`, `DEEPSEEK_TOKEN`, `ANTHROPIC_TOKEN`, `QWEN_HOME_TOKEN`, `METRICS_BACKEND`, `PROMETHEUS_MULTIPROC_DIR`). Change `DB_HOST=database` → `DB_HOST=localhost` so source-mode development (`poetry run python main.py`) works without editing the template.
- **`.env`** (NEW, gitignored): Copy of `.env.example` with one override: `DB_HOST=database` for Docker. This gives `docker-compose` the correct hostname without breaking source-mode defaults.
- **`tests/conftest.py`**: Add 6 new `setdefault` entries for the newly-introduced env vars (`METRICS_BACKEND`, `PROMETHEUS_MULTIPROC_DIR`, `GEMINI_PROD_TOKEN`, `DEEPSEEK_TOKEN`, `ANTHROPIC_TOKEN`, `QWEN_HOME_TOKEN`) with test-safe synthetic values.

## Capabilities

### New Capabilities
- `test-infra-foundation`: Core pytest configuration (asyncio loop scope, per-test timeout, strict markers, marker registry) and environment variable chain (`.env.example` completeness, `.env` for Docker, test conftest alignment).

### Modified Capabilities
<!-- None — this is the first foundational phase; no existing specs are modified. -->

## Impact

- **`pyproject.toml`** — `[tool.pytest.ini_options]` section gains 4 new keys; `[dependency-groups].dev` gains 1 new package.
- **`.env.example`** — grows from 17 to 27 lines (10 → 17 variables).
- **`.env`** — new file, gitignored. 27 lines, identical to `.env.example` except `DB_HOST=database`.
- **`tests/conftest.py`** — `_defaults` dict grows from 11 to 17 entries.
- **`poetry.lock`** — regenerated after `pytest-random-order` addition.
- No API, no database schema, no production code changes. This is purely test infrastructure and environment template changes.
