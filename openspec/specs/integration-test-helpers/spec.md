# integration-test-helpers

A `tests/integration/_helpers.py` module providing `make_mock_request` and `create_mock_provider_config` as importable utilities for integration tests. Replaces the `inject_helpers` autouse fixture pattern that injected these functions into test module namespaces at runtime via `request.module.X = X`.

## Requirements

### Requirement: Helpers are importable from a static module

Integration test files SHALL import `make_mock_request` and `create_mock_provider_config` from `tests.integration._helpers` using standard Python import syntax (`from tests.integration._helpers import make_mock_request`).

#### Scenario: Explicit import resolves statically

- **WHEN** a test file contains `from tests.integration._helpers import make_mock_request`
- **THEN** `ruff check` (F821 rule) SHALL report zero undefined-name errors for `make_mock_request`
- **AND** the import SHALL resolve correctly at runtime under pytest

#### Scenario: Import style follows project conventions

- **WHEN** the import statement is examined
- **THEN** it SHALL use absolute import syntax (`from tests.integration._helpers import ...`)
- **AND** it SHALL NOT use relative import syntax (`from ._helpers import ...`)

### Requirement: inject_helpers fixture is removed

The `inject_helpers` autouse fixture in `tests/integration/conftest.py` SHALL be removed. Test modules SHALL no longer rely on runtime namespace injection via `request.module.X = X`.

#### Scenario: No F821 errors after removal

- **WHEN** `ruff check tests/` is run after all consuming test files have been updated with explicit imports
- **THEN** zero `F821` violations related to `make_mock_request` or `create_mock_provider_config` SHALL be reported

#### Scenario: All integration tests pass after removal

- **WHEN** `pytest tests/integration/ -q --timeout=30 -m "not slow and not postgres"` is run
- **THEN** all tests that previously used `make_mock_request` or `create_mock_provider_config` SHALL pass

### Requirement: Helper functions maintain the same API

The `make_mock_request` and `create_mock_provider_config` functions in `_helpers.py` SHALL have the same signatures, default arguments, and return types as their current definitions in `tests/integration/conftest.py`.

#### Scenario: make_mock_request signature preserved

- **WHEN** `make_mock_request()` is called with no arguments
- **THEN** it SHALL return a `MagicMock(spec=Request)` with the same default state as before (path, method, headers, body, app.state)
- **AND** it SHALL accept optional `url` and `method` keyword arguments

#### Scenario: create_mock_provider_config signature preserved

- **WHEN** `create_mock_provider_config()` is called with no arguments
- **THEN** it SHALL return a `ProviderConfig` with `provider_type="openai_like"`, `debug_mode=DebugMode.DISABLED`, `retry_enabled=False`
- **AND** it SHALL accept optional `provider_type`, `default_model`, `streaming_mode`, `debug_mode`, `retry_enabled`, `retry_on_key_error`, `retry_on_server_error` keyword arguments
