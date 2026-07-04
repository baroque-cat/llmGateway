# ci-pipeline-split

## Purpose

Split the CI pipeline (`.github/workflows/quality.yml`) from a single
monolithic job into 4 parallel jobs, each running the same pytest commands
as the Makefile's process-isolation groups (G1-G5).

## Requirements

### Requirement: CI workflow is split into parallel jobs matching isolation groups

The project SHALL split `.github/workflows/quality.yml` from a single
monolithic job into 4 parallel jobs, each running the same pytest commands
as the Makefile's process-isolation groups.

#### Scenario: CI has a dedicated lint-and-typecheck job

- **WHEN** `.github/workflows/quality.yml` is read
- **THEN** it SHALL contain a `lint-and-typecheck` job
- **AND** the job SHALL run `pyright src/ main.py`
- **AND** the job SHALL run `ruff check src/ tests/ main.py`
- **AND** the job SHALL run `black --check src/ tests/ main.py`

#### Scenario: CI has a dedicated unit-tests job

- **WHEN** `.github/workflows/quality.yml` is read
- **THEN** it SHALL contain a `unit-tests` job
- **AND** the job SHALL run G1 (`tests/unit/` excluding config)
- **AND** the job SHALL run G2 (`tests/unit/config/`)
- **AND** G1 SHALL NOT have a `-` prefix (fail-stops the job)

#### Scenario: CI has a dedicated integration-tests job

- **WHEN** `.github/workflows/quality.yml` is read
- **THEN** it SHALL contain an `integration-tests` job
- **AND** the job SHALL run G3 (`tests/integration/ tests/security/ tests/e2e/`)
- **AND** the job SHALL run G4 (`tests/batching/`)

#### Scenario: CI has a dedicated gatekeeper job

- **WHEN** `.github/workflows/quality.yml` is read
- **THEN** it SHALL contain a `gatekeeper` job
- **AND** the job SHALL run `bash scripts/check-test-hardcodes.sh all`
- **AND** the job SHALL run G5 (root-level tests via inversion)
- **AND** the gatekeeper job SHALL run in parallel with other jobs (no `needs:` dependency)

#### Scenario: CI jobs use the same timeout and marker filters as Makefile

- **WHEN** `.github/workflows/quality.yml` is read
- **THEN** each test job SHALL use `--timeout=30`
- **AND** each test job SHALL use `-m "not slow and not postgres"`
- **AND** G5 SHALL use `--ignore` flags matching the Makefile inversion pattern

### Requirement: CI workflow runs on a nightly schedule

The quality workflow SHALL include a scheduled trigger that runs all jobs
nightly to catch regressions from dependency updates or external changes.

#### Scenario: Nightly CI run at 03:00 UTC

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** the `on` section SHALL include `schedule: cron: '0 3 * * *'`
- **AND** the scheduled run SHALL execute on the default branch (main)
