## ADDED Requirements

### Requirement: Gatekeeper script detects hardcoded test values

The project SHALL provide a `scripts/check-test-hardcodes.sh` script that scans test files for banned patterns and enforces a zero-hardcoded-values policy.

#### Scenario: Canonical mode enforces strict zero-hardcodes in unit tests

- **WHEN** the script runs in `canonical` mode
- **THEN** it SHALL scan `tests/unit/` for all 7 banned-pattern arrays (production URLs, secrets, DB params, gateway ports, provider types, model names, regex patterns)
- **AND** any matching line SHALL be reported as a `CANONICAL VIOLATION` with file path and line number
- **AND** `# boundary:` annotations SHALL be ignored (not a valid exemption in canonical mode)
- **AND** the script SHALL exit with non-zero return code if any violations are found

#### Scenario: Boundary mode implements whitelist via # boundary: annotations

- **WHEN** the script runs in `boundary` mode on `tests/integration/`, `tests/security/`, `tests/e2e/`, or `tests/stress/`
- **THEN** a banned pattern on a line with `# boundary:` on the SAME line SHALL be allowed
- **AND** a banned pattern without annotation SHALL trigger a lookback of up to 20 preceding non-blank lines
- **AND** if a `# boundary:` annotation is found within the lookback window, the pattern SHALL be allowed
- **AND** if no annotation is found, the pattern SHALL be reported as a `BOUNDARY VIOLATION`
- **AND** production URLs (`BANNED_URLS`) SHALL always be banned in ALL modes, even with `# boundary:` annotations

#### Scenario: Root mode enforces strict checks on root-level test files

- **WHEN** the script runs in `root` mode
- **THEN** it SHALL scan only `tests/*.py` files (excluding all subdirectories)
- **AND** any banned pattern SHALL be reported as a `ROOT VIOLATION`
- **AND** `# boundary:` annotations SHALL be ignored (not a valid exemption in root mode)

#### Scenario: All mode runs canonical, boundary, and root sequentially

- **WHEN** the script runs without arguments or with `all` mode
- **THEN** it SHALL execute canonical mode, then boundary mode, then root mode
- **AND** the combined exit code SHALL be non-zero if any mode found violations
- **AND** the combined output SHALL print "All test hardcode checks passed" when all modes pass

#### Scenario: Banned-pattern arrays catch all prohibited values

- **WHEN** the script scans test files
- **THEN** `BANNED_PROD_URLS` SHALL detect: `https://generativelanguage.googleapis.com`, `https://api.anthropic.com`, `https://api.deepseek.com`, `https://dashscope.aliyuncs.com`, `https://api.openai.com`, `https://api.groq.com`
- **AND** `BANNED_SECRETS` SHALL detect: `your_secure_password_here`, `your_secure_metrics_token_here`
- **AND** `BANNED_DB_PARAMS` SHALL detect: `DB_HOST=database`, `DB_USER=llm_gateway`, `DB_NAME=llmgateway`
- **AND** `BANNED_GATEWAY_PORTS` SHALL detect non-canonical port values
- **AND** `BANNED_PROVIDER_TYPES` SHALL detect: `openai` (must be `openai_like`), `deepseek`, `qwen`, `groq`, `claude`, `google`
- **AND** `BANNED_MODEL_NAMES` SHALL detect obsolete model names like `gpt-3.5-turbo`, `gpt-4`, `claude-3-opus`
- **AND** `BANNED_OTHER_REGEX` SHALL detect extended patterns including `password="test_secret"` and `PROMETHEUS_MULTIPROC_DIR=`

#### Scenario: Infrastructure files are excluded from scanning

- **WHEN** the script scans any directory
- **THEN** files in the `EXCLUDE_FILES` list SHALL be skipped
- **AND** `EXCLUDE_FILES` SHALL include: `conftest.py`, `_canonical.py`, `_constants.py`, and all gatekeeper test files themselves

### Requirement: Cache fixtures prevent repeated checker script execution

The project SHALL provide pytest fixtures in `tests/conftest.py` that cache gatekeeper results across the test session.

#### Scenario: _cached_checker_results runs the script once per mode

- **WHEN** pytest starts a session
- **THEN** the `_cached_checker_results` session-scoped fixture SHALL invoke `check-test-hardcodes.sh` once for each of the three modes (`canonical`, `boundary`, `root`)
- **AND** results SHALL be stored as `CheckerResult` namedtuples with fields `returncode`, `stdout`, `stderr`
- **AND** the results dictionary SHALL be wrapped in `types.MappingProxyType` (read-only)
- **AND** the "all" mode SHALL NOT be executed separately — it is composed from the three cached results

#### Scenario: checker_result provides access to cached results

- **WHEN** a test calls `checker_result("canonical")`
- **THEN** it SHALL return the cached `CheckerResult` from `_cached_checker_results`
- **AND** `checker_result("all")` SHALL compose results from all three modes: `returncode = max()` of individual returncodes, `stdout` concatenated with summary lines deduplicated
- **AND** requesting an invalid mode SHALL raise `ValueError`

#### Scenario: _cleanup_stale_temp_files removes leftovers from crashed sessions

- **WHEN** pytest starts a session (before any test)
- **THEN** the `_cleanup_stale_temp_files` autouse session fixture SHALL remove all `tmp*.py` files from the scan directories
- **AND** it SHALL silently handle `OSError` if directories don't exist or files can't be deleted

#### Scenario: _compute_checker_hash reflects file changes

- **WHEN** `_compute_checker_hash()` is called
- **THEN** it SHALL return a sha256 hex digest computed from the checker script content plus all scanned `.py` files
- **AND** it SHALL exclude `__pycache__/` and `__init__.py` files
- **AND** it SHALL deduplicate files across overlapping scan directories
- **AND** the hash SHALL be deterministic (same input → same output)

### Requirement: Structural gatekeeper tests enforce project integrity

The project SHALL include root-level gatekeeper tests that verify project structure, configuration integrity, and documentation consistency.

#### Scenario: test_project_structure validates directory layout

- **WHEN** `test_project_structure.py` runs
- **THEN** it SHALL verify that expected directories exist (`tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/security/`, `tests/batching/`, `tests/stress/`)
- **AND** it SHALL verify that `CanonicalConfig` covers every key in `.env.example` and every section in `config/example_full_config.yaml`

#### Scenario: test_makefile_groups validates Makefile structure

- **WHEN** `test_makefile_groups.py` runs
- **THEN** it SHALL parse the `Makefile` and verify 6 test groups (G1-G6) with correct `--ignore` flags, `--timeout` values, and `-m` marker filters
- **AND** it SHALL verify G1 has no `-` prefix (gate) and G2-G5 have `-` prefix (fault-tolerant)

#### Scenario: test_canonical_integrity verifies CanonicalConfig completeness

- **WHEN** `test_canonical_integrity.py` runs
- **THEN** it SHALL verify that every variable in `.env.example` has a corresponding `CanonicalConfig` field
- **AND** every top-level section in `config/example_full_config.yaml` SHALL have corresponding fields in `CanonicalConfig`

#### Scenario: test_secret_isolation prevents secret leakage

- **WHEN** `test_secret_isolation.py` runs
- **THEN** it SHALL scan the repository for hardcoded tokens, production URLs, and non-canonical passwords
- **AND** it SHALL verify that `.env` is listed in `.gitignore`

#### Scenario: test_env_example validates .env.example completeness

- **WHEN** `test_env_example.py` runs
- **THEN** it SHALL verify `.env.example` contains all 17 required variables
- **AND** it SHALL verify no real API keys or tokens are present (only placeholders and empty strings)

#### Scenario: test_documentation_sync verifies TESTING docs

- **WHEN** `test_documentation_sync.py` runs
- **THEN** it SHALL verify that `TESTING*.md` files reference all test subdirectories
- **AND** it SHALL verify that Makefile targets documented in `TESTING-RUN.md` match the actual Makefile

### Requirement: TESTING documentation covers all test infrastructure

The project SHALL provide four `TESTING*.md` files in the repository root covering writing, running, and enforcing test quality standards.

#### Scenario: TESTING.md serves as the documentation index

- **WHEN** a developer opens `TESTING.md`
- **THEN** it SHALL contain a table linking to `TESTING-GUIDE.md`, `TESTING-RUN.md`, and `TESTING-GATEKEEPER.md`
- **AND** it SHALL provide quick-start commands for common workflows

#### Scenario: TESTING-GUIDE documents the golden rule of zero hardcodes

- **WHEN** a test author reads `TESTING-GUIDE.md`
- **THEN** it SHALL document the Golden Rule: all configuration values in tests must derive from `CanonicalConfig`
- **AND** it SHALL document the `# boundary:` annotation mechanism for boundary tests
- **AND** it SHALL list anti-patterns (hardcoded values, direct `os.environ` manipulation) with examples

#### Scenario: TESTING-RUN documents Makefile targets and isolation groups

- **WHEN** a developer reads `TESTING-RUN.md`
- **THEN** it SHALL document all `make` targets (`test`, `test-slow`, `test-postgres`, `test-all`, `ci`) with timing estimates
- **AND** it SHALL document the 6 process-isolation groups (G1-G6) with their directories, timeouts, and marker filters

#### Scenario: TESTING-GATEKEEPER documents the gatekeeper infrastructure

- **WHEN** a developer reads `TESTING-GATEKEEPER.md`
- **THEN** it SHALL document the 4-mode `check-test-hardcodes.sh` script architecture
- **AND** it SHALL document the cache fixture chain (`_cached_checker_results` → `checker_result` → `CheckerResult`)
- **AND** it SHALL document the 3-tier test classification (clean-codebase, synthetic violation, consistency)
