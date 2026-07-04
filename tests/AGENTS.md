# Test Directory Structure

This directory contains all automated tests for the llmGateway project, organized by test type and mirroring the source code structure. This directory is primarily managed by the **@Mr.Tester** subagent.

For full testing documentation, see:
- [TESTING.md](../TESTING.md) — documentation index
- [TESTING-GUIDE.md](../TESTING-GUIDE.md) — how to write tests (Golden Rule, CanonicalConfig)
- [TESTING-RUN.md](../TESTING-RUN.md) — how to run tests (Makefile targets, G1–G6)
- [TESTING-GATEKEEPER.md](../TESTING-GATEKEEPER.md) — gatekeeper infrastructure

## Working with @Mr.Tester

For all testing activities including creating, modifying, and analyzing test results, always invoke the **@Mr.Tester** subagent. This ensures proper test execution, reporting, and maintains consistency across the test suite.

## Directory Organization

```
tests/
├── _canonical.py              # CanonicalConfig — single source of truth for test config
├── _constants.py              # Shared mock token constants (6 tokens)
├── conftest.py                # Global fixtures (env setup, gatekeeper cache)
├── test_*.py                  # Root-level gatekeeper tests (G5)
├── unit/                      # Unit tests (G1 + G2)
│   ├── config/                # Config schema/loader tests (G2)
│   ├── core/                  # Core functionality unit tests (G1)
│   ├── db/                    # Database layer tests (G1)
│   ├── metrics/               # Metrics tests (G1)
│   ├── providers/             # Provider implementation unit tests (G1)
│   │   └── impl/              # Specific provider implementations
│   └── services/              # Service layer unit tests (G1)
├── integration/               # Integration tests (G3)
├── security/                  # Security tests (G3)
├── e2e/                       # End-to-end tests (G3)
├── batching/                  # Adaptive batching tests (G4)
└── stress/                    # Stress tests (G6, @pytest.mark.slow)
```

## CanonicalConfig

All test configuration values must derive from `CanonicalConfig` — a frozen
dataclass at `tests/_canonical.py` that parses `.env.example` and
`config/example_full_config.yaml` deterministically.

```python
from tests._canonical import CanonicalConfig

cfg = CanonicalConfig.from_example_files()
env = cfg.to_env_dict()  # dict[str, str] of all 17 env vars
```

The autouse fixture `_set_config_vars_from_canonical` in `conftest.py` sets all
17 env vars via `monkeypatch.setenv` before every test. Tests do not need to set
env vars manually.

See [TESTING-GUIDE.md](../TESTING-GUIDE.md) for the Golden Rule and compliance checklist.

## Test Categories

### Unit Tests (G1 + G2)
- Test individual functions, classes, or modules in isolation
- Use comprehensive mocking for external dependencies
- Fast execution with no external service requirements
- Mirror the `src/` directory structure for easy navigation
- **Zero hardcodes** — all values from `CanonicalConfig`

### Integration Tests (G3)
- Test interaction between multiple components or modules
- May involve mocked external services but test internal integration points
- Validate system behavior across module boundaries
- Boundary annotations (`# boundary:`) allowed for legitimate banned-value usage

### Security Tests (G3)
- Auth, credential sanitization, error security
- Boundary annotations allowed

### End-to-End Tests (G3)
- Test complete user flows or system behavior from end to end
- May require external services or live databases
- Boundary annotations allowed

### Batching Tests (G4)
- Adaptive batch controller tests
- Separate process group for event-loop isolation

### Stress Tests (G6)
- Real HTTP/2 server, slow execution
- Only run via `make test-slow`
- Marked with `@pytest.mark.slow`

### Gatekeeper Tests (G5)
- Root-level structural integrity tests (`tests/test_*.py`)
- Verify project structure, config integrity, documentation sync
- Collected via inversion (ignore all subdirectories)

## Running Tests

### Proper Test Execution Protocol

For all testing activities, follow this protocol:
1. **Always use @Mr.Tester** for test execution, creation, and modification
2. **Never run tests manually** without involving @Mr.Tester
3. **Request structured reports** from @Mr.Tester for all test results

### Makefile Targets

```bash
make test          # G1–G5 (~3 s)
make test-slow     # G6 stress tests
make test-all      # G1–G6
make test-postgres # Live PostgreSQL tests
make ci            # lint + typecheck + test
```

See [TESTING-RUN.md](../TESTING-RUN.md) for full details on process-isolation groups.

### Direct pytest

```bash
# Run all tests
poetry run pytest

# Run only unit tests
poetry run pytest tests/unit/

# Run only integration tests
poetry run pytest tests/integration/

# Run specific test file
poetry run pytest tests/unit/core/test_constants.py

# Run with coverage
poetry run pytest --cov=src tests/
```

## Adding New Tests

When adding new tests, follow these guidelines:

1. **Unit Tests**: Place in `tests/unit/` following the same path structure as the corresponding source file in `src/`
2. **Integration Tests**: Place in `tests/integration/` with descriptive names
3. **Security Tests**: Place in `tests/security/`
4. **E2E Tests**: Place in `tests/e2e/`
5. **Batching Tests**: Place in `tests/batching/`
6. **Stress Tests**: Place in `tests/stress/` with `@pytest.mark.slow`
7. **Gatekeeper Tests**: Place at `tests/test_*.py` (root level)

### Pytest Markers

Use the correct markers (not the old `unit`/`integration`/`e2e` markers):

- `@pytest.mark.slow` — stress tests (G6, only via `make test-slow`)
- `@pytest.mark.postgres` — requires live PostgreSQL (`--run-postgres`)
- `@pytest.mark.meta` — meta/structural tests (G5)

### Zero-Hardcodes Compliance

Before committing test code:

1. Use `CanonicalConfig.from_example_files()` for all configuration values
2. Use `tests/_constants.py` for mock tokens
3. Never hardcode DB credentials, provider tokens, or API URLs
4. Use `# boundary:` annotations for legitimate banned-value usage in boundary tests
5. Run `bash scripts/check-test-hardcodes.sh all` — must exit 0

See [TESTING-GUIDE.md](../TESTING-GUIDE.md) for the full compliance checklist.

## Test Discovery

The pytest configuration in `pyproject.toml` automatically discovers tests in all subdirectories under `tests/`, so no additional configuration is needed when adding new test files.
