# ci-pipeline-gatekeeper-tests

## Purpose

Gatekeeper test (`test_ci_pipeline.py`) that performs detailed structural
validation of `.github/workflows/quality.yml` — job presence, parallelism,
step ordering, timeout/marker flags, and trigger configuration.

## Requirements

### Requirement: Gatekeeper test validates CI workflow structure in detail

The project SHALL provide a `test_ci_pipeline.py` root-level gatekeeper test
that performs detailed structural validation of `.github/workflows/quality.yml`
beyond the basic checks in `test_boundary_compliance.py`.

#### Scenario: All 4 required jobs are present

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** the workflow SHALL contain exactly 4 jobs: `lint-and-typecheck`, `unit-tests`, `integration-tests`, `gatekeeper`

#### Scenario: All jobs run in parallel

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** no job SHALL have a `needs` dependency on another job
- **AND** all 4 jobs SHALL have `runs-on: ubuntu-latest`

#### Scenario: Lint job includes tests/ in ruff and black scope

- **WHEN** the `lint-and-typecheck` job steps are inspected
- **THEN** the ruff step SHALL reference `tests/` in its command
- **AND** the black step SHALL reference `tests/` in its command

#### Scenario: Unit-tests job has coverage and codecov steps

- **WHEN** the `unit-tests` job steps are inspected
- **THEN** at least one step SHALL run pytest with `--cov=src`
- **AND** at least one step SHALL use `codecov/codecov-action@v5`
- **AND** the coverage step SHALL have `if: github.event_name == 'push'`

#### Scenario: Gatekeeper job runs checker script before G5 tests

- **WHEN** the `gatekeeper` job steps are inspected
- **THEN** a step SHALL run `bash scripts/check-test-hardcodes.sh all` (without `|| true`)
- **AND** a subsequent step SHALL run G5 pytest with inversion `--ignore` flags

#### Scenario: All test jobs use correct timeout and markers

- **WHEN** any test job (`unit-tests`, `integration-tests`, `gatekeeper`) step runs pytest
- **THEN** the command SHALL include `--timeout=30`
- **AND** the command SHALL include `-m "not slow and not postgres"`

#### Scenario: Workflow has required triggers

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** the `on` section SHALL include `push: branches: [main]`
- **AND** the `on` section SHALL include `pull_request: branches: [main]`
