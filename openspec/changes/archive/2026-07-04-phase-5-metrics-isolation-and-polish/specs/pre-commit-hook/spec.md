## ADDED Requirements

### Requirement: File hygiene hooks enforce repository cleanliness

The project SHALL provide file-hygiene pre-commit hooks from `pre-commit/pre-commit-hooks` that enforce consistent formatting and prevent common mistakes.

#### Scenario: Trailing whitespace is stripped

- **WHEN** a developer attempts to commit a file with trailing whitespace
- **THEN** the `trailing-whitespace` hook SHALL strip trailing whitespace from all text files

#### Scenario: Files end with a single newline

- **WHEN** a developer attempts to commit a file without a trailing newline or with multiple trailing newlines
- **THEN** the `end-of-file-fixer` hook SHALL ensure the file ends with exactly one newline character

#### Scenario: YAML, TOML, and JSON files are syntactically valid

- **WHEN** a YAML, TOML, or JSON file is changed
- **THEN** the corresponding `check-yaml`, `check-toml`, or `check-json` hook SHALL verify the file parses correctly
- **AND** the commit SHALL be blocked if the file has a syntax error

#### Scenario: Merge conflict markers are detected

- **WHEN** a developer attempts to commit a file containing unresolved merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)
- **THEN** the `check-merge-conflict` hook SHALL block the commit

#### Scenario: Private keys are not accidentally committed

- **WHEN** a developer attempts to commit a file containing a private key pattern
- **THEN** the `detect-private-key` hook SHALL block the commit

#### Scenario: Line endings are normalized to LF

- **WHEN** a developer attempts to commit a file with CRLF line endings
- **THEN** the `mixed-line-ending` hook SHALL convert them to LF

### Requirement: Type checking runs in pre-commit for src/

The project SHALL provide a `pyright` pre-commit hook that runs strict type checking on `src/` and `main.py` to catch type errors before reaching CI.

#### Scenario: Pyright runs on changed source files

- **WHEN** a developer modifies a file under `src/` or `main.py`
- **THEN** the `pyright` pre-commit hook SHALL run `poetry run pyright src/ main.py`
- **AND** the hook SHALL use `pass_filenames: false` to ensure pyright has full project context
- **AND** the hook SHALL block the commit if pyright reports errors

### Requirement: Shell scripts are linted with shellcheck

The project SHALL provide a `shellcheck` pre-commit hook that lints shell scripts in the `scripts/` directory.

#### Scenario: Shellcheck validates gatekeeper script

- **WHEN** the `check-test-hardcodes.sh` script is modified
- **THEN** the `shellcheck` hook SHALL lint the script for common shell scripting errors
- **AND** the hook SHALL block the commit if shellcheck reports errors
