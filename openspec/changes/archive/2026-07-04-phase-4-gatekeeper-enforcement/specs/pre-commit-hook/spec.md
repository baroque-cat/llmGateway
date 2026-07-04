## ADDED Requirements

### Requirement: Pre-commit hook blocks commits with hardcoded test values

The project SHALL provide a `.pre-commit-config.yaml` file at the repository root with a `ban-test-hardcodes` hook that runs `check-test-hardcodes.sh` on all test files.

#### Scenario: ban-test-hardcodes hook runs the gatekeeper script authoritatively

- **WHEN** a developer attempts to commit a test file containing a banned pattern
- **THEN** the `ban-test-hardcodes` pre-commit hook SHALL invoke `bash scripts/check-test-hardcodes.sh`
- **AND** the hook SHALL block the commit if the script exits with non-zero return code
- **AND** the hook SHALL scan all files matching `^tests/` (not just staged files, via `pass_filenames: false`)

#### Scenario: ban-test-hardcodes hook is configured as a local hook

- **WHEN** `.pre-commit-config.yaml` is read
- **THEN** the `ban-test-hardcodes` hook SHALL be defined under the `local` repo
- **AND** it SHALL use `language: system`
- **AND** it SHALL have `entry: bash scripts/check-test-hardcodes.sh`

#### Scenario: Ruff check and format hooks cover the full project

- **WHEN** `.pre-commit-config.yaml` is read
- **THEN** it SHALL contain `ruff` and `ruff-format` hooks
- **AND** the ruff hooks SHALL target files matching `^(src|tests|main\.py)/`
