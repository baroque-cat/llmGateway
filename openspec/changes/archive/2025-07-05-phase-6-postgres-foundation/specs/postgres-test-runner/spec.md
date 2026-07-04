## ADDED Requirements

### Requirement: Container lifecycle script manages PostgreSQL test runs

The project SHALL provide a `scripts/run-postgres-tests.sh` script that manages the complete lifecycle of the `test-database` Docker service for running `@pytest.mark.postgres` tests.

#### Scenario: Script detects podman or docker engine

- **WHEN** `run-postgres-tests.sh` is executed
- **THEN** the script SHALL check for `podman` first (via `command -v podman && podman info`)
- **AND** if podman is not available, SHALL check for `docker` (via `command -v docker && docker info`)
- **AND** if neither is available, SHALL print a skip message and exit 0

#### Scenario: Script tears down any existing container before starting

- **WHEN** the script starts
- **THEN** the script SHALL execute `docker compose down -v` (or `podman compose down -v`) with error suppression (`2>/dev/null || true`) to remove any stale container and volumes from previous runs

#### Scenario: Script starts a fresh test-database container

- **WHEN** the script starts the container
- **THEN** the script SHALL execute `docker compose up -d --wait test-database` (or `podman compose up -d --wait test-database`)
- **AND** the script SHALL NOT use `sleep` for readiness (SHALL use `--wait` flag)
- **AND** the script SHALL NOT start the production `database` service

#### Scenario: Script runs postgres tests in groups

- **WHEN** the test-database container is healthy
- **THEN** the script SHALL run all `@pytest.mark.postgres` tests via a `run_group` function
- **AND** each group SHALL run `poetry run pytest <paths> -v --timeout=60 --run-postgres -m "postgres"`
- **AND** the `run_group` function SHALL handle pytest exit code 5 as a non-failure (yellow info message, `EXIT_CODE` unchanged)
- **AND** the `run_group` function SHALL handle pytest exit code `!= 0` (and `!= 5`) as a failure (red message, `EXIT_CODE=1`)
- **AND** test groups SHALL include: schema tests (`tests/integration/db/`), repository tests, manager tests, and gatekeeper policy tests (root-level via inversion)

#### Scenario: Script always tears down after tests complete

- **WHEN** all test groups have finished (regardless of success or failure)
- **THEN** the script SHALL execute `docker compose down -v` (or `podman compose down -v`) WITHOUT error suppression
- **AND** the script SHALL exit with `EXIT_CODE` (0 if all groups passed, 1 if any group failed)

#### Scenario: Script uses v2 compose syntax

- **WHEN** the script invokes compose
- **THEN** the script SHALL use `docker compose` or `podman compose` (space-separated v2 syntax)
- **AND** the script SHALL NOT use `docker-compose` (hyphenated v1 syntax)

### Requirement: Makefile delegates postgres tests to the lifecycle script

The project SHALL update the `test-postgres` Makefile target to delegate to `run-postgres-tests.sh` instead of running pytest inline with `|| true`.

#### Scenario: test-postgres target delegates to script

- **WHEN** `make test-postgres` is executed
- **THEN** the target SHALL run `bash scripts/run-postgres-tests.sh`
- **AND** the target SHALL NOT run `poetry run pytest --run-postgres -m "postgres"` inline
