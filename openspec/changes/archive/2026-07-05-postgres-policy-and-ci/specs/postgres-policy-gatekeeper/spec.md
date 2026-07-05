## ADDED Requirements

### Requirement: All integration db tests must carry @pytest.mark.postgres

The system SHALL verify that every test function in `tests/integration/db/` that
uses `pg_pool.acquire()` or declares a `db_manager` parameter carries the
`@pytest.mark.postgres` decorator.

#### Scenario: Test function using pg_pool without postgres marker is detected

- **WHEN** a test function in `tests/integration/db/test_*.py` calls
  `pg_pool.acquire()` but does NOT have `@pytest.mark.postgres`
- **THEN** the policy test SHALL report that function as a violation with file
  path and line number

#### Scenario: Test function using db_manager fixture without postgres marker is detected

- **WHEN** a test function in `tests/integration/db/test_*.py` declares a
  `db_manager` parameter but does NOT have `@pytest.mark.postgres`
- **THEN** the policy test SHALL report that function as a violation

#### Scenario: Correctly marked test function passes

- **WHEN** a test function in `tests/integration/db/test_*.py` uses
  `pg_pool.acquire()` AND has `@pytest.mark.postgres`
- **THEN** the policy test SHALL NOT report that function as a violation

### Requirement: No mock usage in postgres integration tests

The system SHALL verify that no file in `tests/integration/db/` contains
mock-related imports or calls: `patch("asyncpg.create_pool")`,
`patch("src.db.database.get_pool")`, `MagicMock`, or `AsyncMock`.

#### Scenario: File containing MagicMock is detected

- **WHEN** a file in `tests/integration/db/test_*.py` contains the string
  `MagicMock` or `AsyncMock`
- **THEN** the policy test SHALL report that file as a violation

#### Scenario: File containing asyncpg pool patch is detected

- **WHEN** a file in `tests/integration/db/test_*.py` contains
  `patch("asyncpg.create_pool")` or `patch("src.db.database.get_pool")`
- **THEN** the policy test SHALL report that file as a violation

#### Scenario: Clean file with no mocks passes

- **WHEN** a file in `tests/integration/db/test_*.py` uses only real asyncpg
  connections with no mock-related strings
- **THEN** the policy test SHALL NOT report that file as a violation

### Requirement: run-postgres-tests.sh always starts a fresh container

The system SHALL verify that `scripts/run-postgres-tests.sh` performs a full
container lifecycle: pre-teardown `down -v`, then `up --wait test-database`,
then test execution, then post-teardown `down -v`.

#### Scenario: Script has both pre-teardown and post-teardown down -v calls

- **WHEN** `scripts/run-postgres-tests.sh` is scanned
- **THEN** the script SHALL contain at least 2 `down -v` calls (one
  pre-teardown, one post-teardown)

#### Scenario: Lifecycle ordering is correct

- **WHEN** `scripts/run-postgres-tests.sh` is scanned for ordering
- **THEN** the pre-teardown `down -v` SHALL appear before `up --wait
  test-database`, which SHALL appear before the first `run_group` call, which
  SHALL appear before the final post-teardown `down -v`

### Requirement: run-postgres-tests.sh uses v2 compose syntax

The system SHALL verify that `scripts/run-postgres-tests.sh` uses modern
compose syntax (`podman compose` or `docker compose`, not `docker-compose`),
uses `--wait` instead of `sleep`, and does not contain the deprecated
`docker-compose` command.

#### Scenario: Script uses v2 compose with podman or docker

- **WHEN** `scripts/run-postgres-tests.sh` is scanned
- **THEN** the script SHALL contain `podman compose` or `docker compose`
- **AND** the script SHALL NOT contain `docker-compose`

#### Scenario: Script uses --wait not sleep

- **WHEN** `scripts/run-postgres-tests.sh` is scanned
- **THEN** the script SHALL contain `--wait`
- **AND** the script SHALL NOT contain `sleep`

### Requirement: Makefile test-postgres delegates to shell script

The system SHALL verify that the Makefile `test-postgres` target delegates to
`bash scripts/run-postgres-tests.sh` rather than running pytest directly.

#### Scenario: Makefile delegates to the script

- **WHEN** the `Makefile` is scanned
- **THEN** the `test-postgres` target SHALL contain `bash
  scripts/run-postgres-tests.sh`
- **AND** the target SHALL NOT contain `poetry run pytest --run-postgres`
