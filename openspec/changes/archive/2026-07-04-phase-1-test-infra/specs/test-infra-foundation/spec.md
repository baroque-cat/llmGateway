## ADDED Requirements

### Requirement: Session-scoped async fixtures receive a session-scoped event loop

The test infrastructure SHALL configure pytest-asyncio so that async fixtures with `scope="session"` use a session-scoped asyncio event loop, preventing `ScopeMismatchError` and teardown hangs.

#### Scenario: Stress test server factory starts without error

- **WHEN** `http2_server_factory` (`@pytest_asyncio.fixture(scope="session")`) is requested by a stress test
- **THEN** the fixture's event loop SHALL remain alive for the duration of the session, including fixture teardown
- **AND** `await s.stop()` during teardown SHALL complete without hanging

#### Scenario: Function-scoped async fixtures are unaffected

- **WHEN** a function-scoped async fixture (`@pytest_asyncio.fixture` or `@pytest_asyncio.fixture(scope="function")`) is requested
- **THEN** the fixture SHALL use the default function-scoped event loop
- **AND** the event loop SHALL be fresh for each test function

### Requirement: Every test has a global per-test timeout of 30 seconds

The test infrastructure SHALL enforce a global per-test timeout of 30 seconds so that any test that hangs is killed rather than blocking the entire test suite indefinitely.

#### Scenario: Test that hangs is killed after 30 seconds

- **WHEN** a test runs for more than 30 seconds without completing
- **THEN** pytest-timeout SHALL raise `TimeoutError` and mark the test as failed
- **AND** subsequent tests SHALL continue executing

#### Scenario: Test with per-test timeout override uses its own value

- **WHEN** a test has `@pytest.mark.timeout(120)`
- **THEN** the per-test timeout value (120s) SHALL take precedence over the global value (30s)

### Requirement: All pytest markers used by the project are registered

The test infrastructure SHALL register all custom markers in `pyproject.toml` under `[tool.pytest.ini_options].markers` so that `--strict-markers` can detect typos and unregistered markers.

#### Scenario: Unknown marker produces an error

- **WHEN** a test is decorated with `@pytest.mark.unknown_marker` and `--strict-markers` is active (via `addopts`)
- **THEN** pytest SHALL raise `PytestUnknownMarkWarning`

#### Scenario: Registered markers do not produce warnings

- **WHEN** a test uses `@pytest.mark.slow`, `@pytest.mark.postgres`, or `@pytest.mark.meta`
- **THEN** pytest SHALL NOT produce any marker-related warnings

### Requirement: .env.example contains all environment variables required by the application

The `.env.example` file SHALL list every environment variable that the application reads from `os.environ` at runtime, including variables read directly by subsystems that bypass the YAML/Pydantic config chain.

#### Scenario: All env vars required by the config loader are present

- **WHEN** `ConfigLoader` resolves `${VAR}` placeholders
- **THEN** every `${VAR}` referenced in `config/example_full_config.yaml` and `src/config/defaults.py` SHALL have a corresponding entry in `.env.example`

#### Scenario: Metrics subsystem env vars are present

- **WHEN** `src/metrics/__init__.py` reads `METRICS_BACKEND` from `os.environ`
- **THEN** `.env.example` SHALL contain `METRICS_BACKEND=` with an empty default value

#### Scenario: Provider-specific tokens are present

- **WHEN** `config/example_full_config.yaml` references `${GEMINI_PROD_TOKEN}`, `${DEEPSEEK_TOKEN}`, `${ANTHROPIC_TOKEN}`, `${QWEN_HOME_TOKEN}`
- **THEN** `.env.example` SHALL contain each token variable with an empty default value

### Requirement: DB_HOST uses localhost in .env.example and database in .env

The committed `.env.example` template SHALL use `DB_HOST=localhost` so that source-mode development (`poetry run python main.py`) works without editing. A gitignored `.env` file SHALL override to `DB_HOST=database` for Docker Compose deployments.

#### Scenario: Source-mode development works with .env.example defaults

- **WHEN** a developer runs `poetry run python main.py gateway` without creating a `.env` file
- **THEN** the config loader SHALL resolve `DB_HOST=localhost` from `.env.example`

#### Scenario: Docker Compose gets the correct hostname from .env

- **WHEN** `docker-compose up` is invoked and `.env` contains `DB_HOST=database`
- **THEN** the `gateway` and `keeper` containers SHALL connect to the `database` service via the Docker network hostname

#### Scenario: .env is gitignored

- **WHEN** `git status` is run after creating `.env`
- **THEN** `.env` SHALL NOT appear as an untracked or modified file

### Requirement: tests/conftest.py provides fallback env vars for all variables in .env.example

The root `tests/conftest.py` SHALL use `os.environ.setdefault()` to provide test-safe synthetic values for every variable listed in `.env.example`, so that tests running without explicit env var setup do not fail on missing variables.

#### Scenario: Config loader test gets all required env vars from conftest

- **WHEN** `test_loader.py` runs without setting any env vars
- **THEN** all `${VAR}` references resolved by `_resolve_env_vars()` SHALL have non-None values (no `ValueError` for missing vars)

#### Scenario: Newly added env vars are covered by conftest defaults

- **WHEN** `GEMINI_PROD_TOKEN`, `DEEPSEEK_TOKEN`, `ANTHROPIC_TOKEN`, `QWEN_HOME_TOKEN`, `METRICS_BACKEND`, `PROMETHEUS_MULTIPROC_DIR` are added to `.env.example`
- **THEN** `tests/conftest.py` `_defaults` dict SHALL contain a corresponding entry for each
