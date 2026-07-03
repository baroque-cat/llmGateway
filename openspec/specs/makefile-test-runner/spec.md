# makefile-test-runner

## Purpose

Defines the Makefile-based test orchestration for the llmGateway project. The Makefile provides process-isolated test groups (fresh asyncio event loop per group), per-group timeouts, marker filters, and standardized developer workflows including `make test`, `make test-slow`, `make test-postgres`, `make test-all`, and `make ci`.

## Requirements

### Requirement: Makefile provides process-isolated test groups

The project SHALL include a Makefile that runs tests in separate `poetry run pytest` invocations (process isolation), each with a fresh asyncio event loop, preventing cross-contamination between test groups.

#### Scenario: `make test` runs G1 through G5

- **WHEN** a developer runs `make test`
- **THEN** G1 (unit tests excluding config) SHALL run as the gate group — if G1 fails, subsequent groups SHALL NOT execute
- **AND** G2 (config tests), G3 (integration+security+e2e), G4 (batching), and G5 (root-level) SHALL run with fault tolerance — a group failure SHALL NOT abort subsequent groups
- **AND** each group SHALL receive `--timeout=30` and marker filter `-m "not slow and not postgres"`

#### Scenario: `make test-slow` runs G6 stress tests only

- **WHEN** a developer runs `make test-slow`
- **THEN** G6 SHALL execute `tests/stress/` with `--timeout=60` and marker filter `-m slow`
- **AND** G6 SHALL NOT be included in `make test`

#### Scenario: G5 collects root-level tests via inversion

- **WHEN** G5 executes `pytest tests/`
- **THEN** it SHALL exclude `tests/unit/`, `tests/integration/`, `tests/security/`, `tests/e2e/`, `tests/stress/`, and `tests/batching/` via `--ignore` flags
- **AND** the remaining tests (root-level `.py` files) SHALL be collected

#### Scenario: `make test-postgres` runs postgres-marked tests

- **WHEN** a developer runs `make test-postgres` with `--run-postgres` flag
- **THEN** pytest SHALL collect and run only tests marked with `@pytest.mark.postgres`
- **AND** tests without the postgres marker SHALL be deselected

#### Scenario: `make test-all` runs full suite

- **WHEN** a developer runs `make test-all`
- **THEN** G1-G5 (`make test`) SHALL execute first
- **AND** G6 (`make test-slow`) SHALL execute after
- **AND** the command SHALL print "All tests complete" on success

#### Scenario: `make ci` runs lint, typecheck, and test

- **WHEN** a developer runs `make ci`
- **THEN** `poetry run ruff check src/ tests/` SHALL execute first
- **AND** `poetry run pyright` SHALL execute second
- **AND** `make test` (G1-G5) SHALL execute third
- **AND** any failure SHALL abort the pipeline (no `-` prefix on ci targets)

### Requirement: --run-postgres CLI hook enables opt-in postgres tests

The root `tests/conftest.py` SHALL register a `--run-postgres` CLI flag via `pytest_addoption`. When present, postgres-marked tests SHALL execute. When absent, postgres-marked tests SHALL be skipped with reason "--run-postgres not specified".

#### Scenario: Postgres tests are skipped by default

- **WHEN** pytest runs without `--run-postgres`
- **THEN** every test decorated with `@pytest.mark.postgres` SHALL be skipped
- **AND** the skip reason SHALL be "--run-postgres not specified"

#### Scenario: Postgres tests execute with --run-postgres flag

- **WHEN** pytest runs with `--run-postgres` and `-m "postgres"`
- **THEN** only tests decorated with `@pytest.mark.postgres` SHALL be collected and executed

### Requirement: test_batching directory is renamed to batching

The `tests/test_batching/` directory SHALL be renamed to `tests/batching/` to match the naming convention of all other test subdirectories (`unit/`, `integration/`, `e2e/`, `security/`, `stress/`).

#### Scenario: Batching tests are discoverable at new path

- **WHEN** pytest collects tests from `tests/batching/`
- **THEN** all 5 test modules (plus `__init__.py`) SHALL be discovered
- **AND** no import errors or module-not-found errors SHALL occur

#### Scenario: No references to the old path remain

- **WHEN** the rename is complete
- **THEN** no source file SHALL import from `tests.test_batching` (verified: zero such imports exist)
