# test-database-service

## Purpose

Docker Compose `test-database` service (PostgreSQL 18 on port 5433) for
local postgres integration tests (`make test-postgres`), using test-safe
credentials matching CanonicalConfig.

## Requirements

### Requirement: Docker Compose provides a dedicated test database service

The project SHALL provide a `test-database` service in `docker-compose.yml`
for local postgres integration tests, using test-safe credentials on a
non-conflicting port.

#### Scenario: test-database service is available on port 5433

- **WHEN** `docker compose up -d test-database` is run
- **THEN** a PostgreSQL 18 database SHALL be accessible on `localhost:5433`
- **AND** the database SHALL run on the `postgres:18-alpine` image

#### Scenario: test-database uses test-safe credentials

- **WHEN** the `test-database` service is started
- **THEN** the database user SHALL be `test_user`
- **AND** the password SHALL be `test_password`
- **AND** the database name SHALL be `test_db`
- **AND** these credentials SHALL match CanonicalConfig's test-safe overrides

#### Scenario: test-database does not conflict with production database

- **WHEN** the production `database` service (port 5432) and `test-database`
  service (port 5433) are both started
- **THEN** both SHALL be accessible simultaneously
- **AND** the `test-database` service SHALL NOT interfere with production data

#### Scenario: Integration tests can connect to test-database

- **WHEN** `make test-postgres` is run with `--run-postgres`
- **THEN** postgres-marked tests SHALL connect to the `test-database` service
- **AND** tests SHALL complete without `ConnectionRefusedError`
