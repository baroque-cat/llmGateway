# postgres-ci-integration

## Purpose

Nightly CI job (`postgres-integration`) in `.github/workflows/quality.yml` that runs the full PostgreSQL integration test suite against a real database container. Triggered on `schedule` (03:00 UTC daily) and `workflow_dispatch` only — not on every push. The gatekeeper tests (`test_ci_pipeline.py` and `test_hardcode_checker_regression.py`) validate the job configuration and ensure regression test lists are kept up to date.

## Requirements

### Requirement: CI workflow has a postgres-integration job

The system SHALL provide a `postgres-integration` CI job in
`.github/workflows/quality.yml` that runs the full PostgreSQL integration test
suite on a schedule and on manual dispatch.

#### Scenario: Job runs on schedule and workflow_dispatch only

- **WHEN** the CI workflow is triggered by a `push` or `pull_request` event
- **THEN** the `postgres-integration` job SHALL NOT execute
- **AND** when triggered by `schedule` or `workflow_dispatch`, the job SHALL
  execute

#### Scenario: Job starts test database, runs tests, and tears down

- **WHEN** the `postgres-integration` job executes
- **THEN** it SHALL start the `test-database` container with `docker compose up
  -d --wait test-database`
- **AND** it SHALL run `bash scripts/run-postgres-tests.sh`
- **AND** it SHALL tear down the container with `docker compose down -v`
  (guaranteed by `if: always()`)

#### Scenario: Job uses the same Python version as other CI jobs

- **WHEN** the `postgres-integration` job is configured
- **THEN** it SHALL use Python `3.13.5` via `actions/setup-python@v5`

#### Scenario: Job is listed in the required jobs list

- **WHEN** the `postgres-integration` job exists in `quality.yml`
- **THEN** the gatekeeper test `test_ci_pipeline.py` SHALL recognize it as a
  required job (present in `_REQUIRED_JOBS`)

### Requirement: Gatekeeper test lists are updated for the new policy file

The system SHALL verify that `tests/test_hardcode_checker_regression.py`
includes `test_postgres_policy.py` in its `_GATEKEEPER_TEST_FILES` list.

#### Scenario: Policy file is in the gatekeeper regression test list

- **WHEN** `test_exclude_files_covers_all_gatekeeper_tests` runs
- **THEN** `test_postgres_policy.py` SHALL be present in
  `_GATEKEEPER_TEST_FILES`
