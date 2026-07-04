## ADDED Requirements

### Requirement: BANNED_OTHER_REGEX includes non-canonical DB password pattern

The gatekeeper script SHALL include a regex pattern that detects `DatabaseConfig(...)` constructor calls where the `password=` keyword argument is not the canonical test value `test_password`.

#### Scenario: Non-canonical DB password in source is detected

- **WHEN** the gatekeeper script scans test files in canonical mode
- **THEN** the pattern `DatabaseConfig\(.*password="(?!test_password)"` SHALL be present in the `BANNED_OTHER_REGEX` array
- **AND** any source line matching `DatabaseConfig(...password="not_test_password"...)` SHALL be flagged as a violation
- **AND** any source line matching `DatabaseConfig(...password="test_password"...)` SHALL NOT be flagged (canonical value permitted)

### Requirement: BANNED_OTHER_REGEX includes httpcore version enforcement pattern

The gatekeeper script SHALL include a regex pattern that detects httpcore version assertions that are not the pinned canonical version `1.0.9`.

#### Scenario: Non-canonical httpcore version is detected

- **WHEN** the gatekeeper script scans test files in canonical mode
- **THEN** the pattern `httpcore[^.]*version.*[^1][^.]*[^0][^.]*[^9]` SHALL be present in the `BANNED_OTHER_REGEX` array
- **AND** any test asserting `httpcore.__version__ == '1.0.10'` or similar SHALL be flagged as a violation
- **AND** any test asserting `httpcore.__version__ == '1.0.9'` SHALL NOT be flagged (canonical version permitted)

### Requirement: EXCLUDE_FILES includes future postgres policy test

The gatekeeper script SHALL pre-register `test_postgres_policy.py` in its `EXCLUDE_FILES` array so that the upcoming Block 6 policy enforcement gatekeeper is not flagged for containing banned patterns used as test assertions.

#### Scenario: test_postgres_policy.py is excluded from scanning

- **WHEN** the gatekeeper script runs in any mode
- **THEN** `test_postgres_policy.py` SHALL be present in the `EXCLUDE_FILES` array
- **AND** the file SHALL be excluded from all pattern checks (it may contain Docker compose command strings, DSN patterns, and other gatekeeper assertion data)
