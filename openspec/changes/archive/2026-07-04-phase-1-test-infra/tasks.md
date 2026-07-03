## 1. Git & Environment

- [x] 1.1 Create a new git branch: `git checkout -b test-ref`
- [x] 1.2 Run `poetry run pytest --co -q` to verify all tests can be collected before changes

## 2. pyproject.toml — Critical pytest fixes

- [x] 2.1 Add `asyncio_default_fixture_loop_scope = "session"` to `[tool.pytest.ini_options]` (fixes root cause of stress test hangs — session-scoped `http2_server_factory` getting wrong event loop)
- [x] 2.2 Add `timeout = 30` to `[tool.pytest.ini_options]` (global per-test timeout — kills any test hung >30s)
- [x] 2.3 Add `addopts = ["--strict-markers", "--strict-config"]` to `[tool.pytest.ini_options]`
- [x] 2.4 Expand `markers` list: add `postgres` and `meta` markers alongside existing `slow`
- [x] 2.5 Add `"pytest-random-order (>=1.1.0,<2.0.0)"` to `[dependency-groups].dev`
- [x] 2.6 Run `poetry lock --no-update && poetry install --with dev` to install new dependency

## 3. .env.example — Complete the environment variable template

- [x] 3.1 Change `DB_HOST=database #for containers` → `DB_HOST=localhost # change to "database" in .env for Docker`
- [x] 3.2 Add `METRICS_BACKEND=` with comment explaining "prometheus" or "" (memory/disabled)
- [x] 3.3 Add `PROMETHEUS_MULTIPROC_DIR=` with comment explaining keeper/gateway usage
- [x] 3.4 Add `LLM_PROVIDER_DEFAULT_TOKEN=` section (used when provider config does not specify its own token)
- [x] 3.5 Add `GEMINI_PROD_TOKEN=`, `DEEPSEEK_TOKEN=`, `ANTHROPIC_TOKEN=`, `QWEN_HOME_TOKEN=` section
- [x] 3.6 Verify `.env.example` has exactly 17 variables (count `=` lines)

## 4. .env — Create Docker-ready environment file

- [x] 4.1 Run `cp .env.example .env`
- [x] 4.2 Change `DB_HOST=localhost` → `DB_HOST=database` in `.env`
- [x] 4.3 Verify `.env` is gitignored: `git check-ignore .env` should exit 0

## 5. tests/conftest.py — Align setdefault dict with expanded .env.example

- [x] 5.1 Add `"METRICS_BACKEND": ""` to `_defaults` dict
- [x] 5.2 Add `"PROMETHEUS_MULTIPROC_DIR": ""` to `_defaults` dict
- [x] 5.3 Add `"GEMINI_PROD_TOKEN": "test_gemini_token"` to `_defaults` dict
- [x] 5.4 Add `"DEEPSEEK_TOKEN": "test_deepseek_token"` to `_defaults` dict
- [x] 5.5 Add `"ANTHROPIC_TOKEN": "test_anthropic_token"` to `_defaults` dict
- [x] 5.6 Add `"QWEN_HOME_TOKEN": "test_qwen_token"` to `_defaults` dict
- [x] 5.7 Verify `_defaults` dict has 17 entries (match `.env.example` variable count)

## 6. Verification

- [x] 6.1 Run `poetry run pytest --co -q` — verify all tests collect without warnings (no `PytestUnknownMarkWarning`, no import errors)
- [x] 6.2 Run `poetry run pytest tests/unit/config/test_loader.py -q --timeout=30` — verify config loader tests pass (no `ValueError` for missing env vars)
- [x] 6.3 Run `poetry run pytest tests/stress/test_ephemeral_server.py -q --timeout=60` — verify stress test fixture no longer hangs
- [x] 6.4 Run `poetry run pytest tests/stress/ -q --timeout=60 -m slow` — verify full stress suite no longer hangs
- [x] 6.5 Run static verification on `.env.example`: `grep -c '=' .env.example` should print `17`
- [x] 6.6 Run static verification on `pyproject.toml`: `grep 'asyncio_default_fixture_loop_scope' pyproject.toml` should print a matching line
- [x] 6.7 Run static verification on `pyproject.toml`: `grep 'timeout = 30' pyproject.toml` should print a matching line
