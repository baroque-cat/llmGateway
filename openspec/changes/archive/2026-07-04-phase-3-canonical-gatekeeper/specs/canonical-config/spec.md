## ADDED Requirements

### Requirement: CanonicalConfig provides a single source of truth for test configuration

The project SHALL provide a `CanonicalConfig` frozen dataclass at `tests/_canonical.py` that parses `.env.example` and `config/example_full_config.yaml` deterministically at import time. This replaces the implicit `os.environ.setdefault()` fallback pattern in `tests/conftest.py`.

#### Scenario: CanonicalConfig parses example files correctly

- **WHEN** `CanonicalConfig.from_example_files()` is called
- **THEN** it SHALL read `.env.example` and parse all `KEY=VALUE` lines, skipping comments and blank lines
- **AND** it SHALL read `config/example_full_config.yaml` via `ruamel.yaml` and resolve `${VAR}` and `${VAR:-default}` placeholders
- **AND** it SHALL return a frozen dataclass instance with ~50 typed fields covering all configuration sections (database, gateway, keeper, http_client, timeouts, metrics, provider tokens, adaptive batching, health policy)
- **AND** the returned instance SHALL be immutable (frozen=True) — attempts to modify fields SHALL raise `FrozenInstanceError`

#### Scenario: CanonicalConfig replaces setdefault in conftest.py

- **WHEN** pytest loads `tests/conftest.py`
- **THEN** a `canonical_config` session-scoped fixture SHALL return `CanonicalConfig.from_example_files()` once per session
- **AND** an autouse `_set_config_vars_from_canonical` fixture SHALL call `monkeypatch.setenv` for all 17 environment variables before every test
- **AND** the old `_setup_default_env_vars()` function and its module-level call SHALL be removed
- **AND** all existing tests SHALL continue to pass with the same environment variable values

#### Scenario: Duplicated _BASE_ENV dicts are replaced

- **WHEN** config test files in `tests/unit/config/` set up their environment
- **THEN** they SHALL use `CanonicalConfig.from_example_files()` instead of copy-pasted `_BASE_ENV` dictionaries
- **AND** the number of duplicated `_BASE_ENV` occurrences SHALL reduce from 10+ to 0

#### Scenario: CanonicalConfig is import-safe from any test file

- **WHEN** any test file imports `from tests._canonical import CanonicalConfig`
- **THEN** the import SHALL succeed without side effects
- **AND** `CanonicalConfig.from_example_files()` SHALL return consistent values regardless of which test file calls it
- **AND** module-level caching SHALL ensure `.env.example` and `config/example_full_config.yaml` are parsed only once

### Requirement: Shared test constants are centralized

The project SHALL provide a `tests/_constants.py` module containing shared mock token values.

#### Scenario: Mock tokens are accessible from _constants

- **WHEN** a test file imports `from tests._constants import MOCK_GEMINI_TOKEN`
- **THEN** it SHALL receive the canonical mock token string `"test_gemini_token"`
- **AND** all 6 mock tokens (GEMINI, DEEPSEEK, ANTHROPIC, QWEN, DEFAULT, METRICS) SHALL be defined as typed module-level constants

#### Scenario: _constants replaces duplicated mock values

- **WHEN** test files need mock provider tokens
- **THEN** they SHALL import from `tests._constants` rather than defining their own string literals
- **AND** the `_defaults` dict in `conftest.py` SHALL import mock values from `tests._constants` if they remain needed after the CanonicalConfig migration
