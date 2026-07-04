## ADDED Requirements

### Requirement: CI workflow runs on a nightly schedule

The quality workflow SHALL include a scheduled trigger that runs all jobs nightly to catch regressions from dependency updates or external changes.

#### Scenario: Nightly CI run at 03:00 UTC

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** the `on` section SHALL include `schedule: cron: '0 3 * * *'`
- **AND** the scheduled run SHALL execute on the default branch (main)
