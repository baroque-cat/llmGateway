## ADDED Requirements

### Requirement: Metrics keeper test is relocated to tests/unit/metrics/

The project SHALL relocate `tests/unit/services/test_keeper_metrics.py` to `tests/unit/metrics/test_keeper_metrics.py` and move the shared `mock_run_keeper_dependencies` fixture to `tests/unit/conftest.py` so that both `tests/unit/services/` and `tests/unit/metrics/` subtrees have access to it.

#### Scenario: test_keeper_metrics.py is in the metrics directory

- **WHEN** `tests/unit/metrics/` directory is inspected
- **THEN** `test_keeper_metrics.py` SHALL exist at `tests/unit/metrics/test_keeper_metrics.py`
- **AND** `tests/unit/services/test_keeper_metrics.py` SHALL NOT exist

#### Scenario: mock_run_keeper_dependencies fixture is accessible from both subtrees

- **WHEN** tests in `tests/unit/services/` run
- **THEN** the `mock_run_keeper_dependencies` fixture SHALL be discoverable (defined in `tests/unit/conftest.py`)
- **AND** tests in `tests/unit/metrics/test_keeper_metrics.py` SHALL also have access to the same fixture

#### Scenario: Existing keeper tests continue to pass after fixture relocation

- **WHEN** `pytest tests/unit/services/test_keeper.py tests/unit/services/test_keeper_export_jobs.py -v` is executed
- **THEN** all tests SHALL pass (they continue to use `mock_run_keeper_dependencies` from the new location)

### Requirement: Makefile has standalone gatekeeper and boundary targets

The project SHALL add `test-gatekeeper` and `test-boundary` standalone Makefile targets that allow running the gatekeeper test suite and boundary compliance check independently of the full `make test` suite.

#### Scenario: test-gatekeeper runs root-level tests only

- **WHEN** `make test-gatekeeper` is executed
- **THEN** the target SHALL run `poetry run pytest tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching -q --timeout=30 -m "not slow and not postgres"`

#### Scenario: test-boundary runs a single file fast check

- **WHEN** `make test-boundary` is executed
- **THEN** the target SHALL run `poetry run pytest tests/test_boundary_compliance.py -q --timeout=30`

### Requirement: tests/integration/db/ directory exists as scaffold

The project SHALL create the `tests/integration/db/` directory with an `__init__.py` file as a scaffold for future PostgreSQL integration tests (Blocks 2-5).

#### Scenario: Directory structure exists

- **WHEN** `tests/integration/db/` is inspected
- **THEN** the directory SHALL exist
- **AND** it SHALL contain an `__init__.py` file (may be empty)
