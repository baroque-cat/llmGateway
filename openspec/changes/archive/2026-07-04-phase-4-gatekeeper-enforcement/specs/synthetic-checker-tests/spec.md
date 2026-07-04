## ADDED Requirements

### Requirement: Tier 2 synthetic violation tests verify checker mode-specific detection

The project SHALL provide root-level gatekeeper tests that create temporary `.py` files with banned patterns and verify that `check-test-hardcodes.sh` detects them in the correct mode.

#### Scenario: Canonical mode detects banned patterns in synthetic test files

- **WHEN** a temporary `.py` file containing a banned production URL, secret, DB parameter, model name, provider type pattern, or gateway port is placed in `tests/unit/`
- **AND** `check-test-hardcodes.sh` is run in `canonical` mode via direct `subprocess.run()`
- **THEN** the script SHALL exit with non-zero return code
- **AND** the output SHALL contain `CANONICAL VIOLATION` for each banned pattern

#### Scenario: Boundary mode allows banned patterns with # boundary: annotation

- **WHEN** a temporary `.py` file with a banned pattern annotated with `# boundary:` on the same line is placed in `tests/integration/`
- **AND** `check-test-hardcodes.sh` is run in `boundary` mode
- **THEN** the script SHALL exit with zero return code
- **AND** the output SHALL NOT contain `BOUNDARY VIOLATION` for the annotated line

#### Scenario: Boundary mode rejects banned patterns without annotation

- **WHEN** a temporary `.py` file with a banned pattern WITHOUT `# boundary:` annotation is placed in `tests/integration/`
- **AND** `check-test-hardcodes.sh` is run in `boundary` mode
- **THEN** the script SHALL exit with non-zero return code
- **AND** the output SHALL contain `BOUNDARY VIOLATION` for the unannotated line

#### Scenario: Production URLs are always banned even with annotation

- **WHEN** a temporary `.py` file with a production URL annotated with `# boundary:` is placed in any scan directory
- **AND** `check-test-hardcodes.sh` is run in `boundary` mode
- **THEN** the script SHALL exit with non-zero return code
- **AND** the output SHALL contain `BOUNDARY VIOLATION` with `(always banned)` for the production URL

#### Scenario: Root mode detects banned patterns in root-level test files

- **WHEN** a temporary `.py` file containing a banned pattern is placed in the `tests/` root directory
- **AND** `check-test-hardcodes.sh` is run in `root` mode
- **THEN** the script SHALL exit with non-zero return code
- **AND** the output SHALL contain `ROOT VIOLATION`

#### Scenario: All mode composes results from multiple directories

- **WHEN** synthetic violation files are placed in both `tests/unit/` and `tests/` root
- **AND** `check-test-hardcodes.sh` is run in `all` mode
- **THEN** the script SHALL detect violations from all three component modes

### Requirement: Regression tests prevent false positives and ensure output consistency

The project SHALL provide regression tests verifying the checker produces zero false positives on the clean codebase and deterministic output across runs.

#### Scenario: Clean codebase produces zero violations in all modes

- **WHEN** `check-test-hardcodes.sh` is run in `canonical`, `boundary`, `root`, and `all` modes against the clean codebase
- **THEN** all four modes SHALL exit with return code 0
- **AND** the output SHALL contain "All test hardcode checks passed"

#### Scenario: Checker output is deterministic across runs

- **WHEN** `check-test-hardcodes.sh` is run twice with the same mode on the same codebase
- **THEN** the normalized output (excluding timing-sensitive lines) SHALL be identical

#### Scenario: No-args invocation equals all mode

- **WHEN** `check-test-hardcodes.sh` is run without arguments
- **THEN** it SHALL produce the same output as running with `all` mode explicitly

### Requirement: Boundary compliance tests verify annotations and infrastructure config

The project SHALL provide a boundary compliance test file that verifies `# boundary:` annotations on real test files and validates pre-commit/CI infrastructure configuration.

#### Scenario: Boundary mode passes on clean codebase

- **WHEN** `checker_result("boundary")` is accessed via the cached fixture
- **THEN** the return code SHALL be 0

#### Scenario: Removing a boundary annotation triggers a violation

- **WHEN** a boundary test file's `# boundary:` annotation is removed from a banned-pattern line
- **AND** the corrupted file is scanned
- **THEN** a `BOUNDARY VIOLATION` SHALL be reported for the now-unannotated pattern

#### Scenario: Pre-commit hook configuration is valid

- **WHEN** `.pre-commit-config.yaml` is parsed
- **THEN** it SHALL contain a `ban-test-hardcodes` hook under the `local` repo
- **AND** the hook SHALL have `entry: bash scripts/check-test-hardcodes.sh`
- **AND** the hook SHALL have `files: ^tests/`
- **AND** the hook SHALL have `pass_filenames: false`

#### Scenario: CI workflow contains gatekeeper job

- **WHEN** `.github/workflows/quality.yml` is parsed
- **THEN** it SHALL contain a `gatekeeper` job
- **AND** the gatekeeper job SHALL run `check-test-hardcodes.sh all`
- **AND** the gatekeeper job SHALL run G5 pytest (root-level tests via inversion)

### Requirement: Cache fixture meta-tests verify performance and correctness

The project SHALL expand `test_conftest_checker_cache.py` with hash coverage tests, performance budgets, and fixture correctness checks.

#### Scenario: _compute_checker_hash covers script content

- **WHEN** the checker script content changes
- **THEN** `_compute_checker_hash()` SHALL return a different hash

#### Scenario: _compute_checker_hash covers scanned test files

- **WHEN** a `.py` file is added to a scan directory
- **THEN** `_compute_checker_hash()` SHALL return a different hash

#### Scenario: _compute_checker_hash excludes __pycache__

- **WHEN** a file is added to `__pycache__/` in a scan directory
- **THEN** `_compute_checker_hash()` SHALL NOT change

#### Scenario: _compute_checker_hash is deterministic

- **WHEN** `_compute_checker_hash()` is called twice on the same codebase
- **THEN** it SHALL return the same hash both times

#### Scenario: Hash computation completes within sub-second budget

- **WHEN** `_compute_checker_hash()` is called
- **THEN** it SHALL complete in under 1.0 seconds

#### Scenario: Cache startup completes within time budget

- **WHEN** the `_cached_checker_results` fixture is first accessed
- **THEN** it SHALL complete in under 10.0 seconds

#### Scenario: checker_result all mode matches direct subprocess

- **WHEN** `checker_result("all")` is called
- **THEN** the composed result SHALL match a direct `subprocess.run` call of the checker in `all` mode
