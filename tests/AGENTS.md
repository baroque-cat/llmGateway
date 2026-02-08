# Test Directory Structure

This directory contains all automated tests for the llmGateway project, organized by test type and mirroring the source code structure. This directory is primarily managed by the **@Mr.Tester** subagent.

## Working with @Mr.Tester

For all testing activities including creating, modifying, and analyzing test results, always invoke the **@Mr.Tester** subagent. This ensures proper test execution, reporting, and maintains consistency across the test suite.

## Directory Organization

```
tests/
├── unit/                    # Unit tests (individual functions/classes in isolation)
│   ├── config/             # Configuration-related unit tests
│   ├── core/               # Core functionality unit tests  
│   ├── providers/          # Provider implementation unit tests
│   │   └── impl/           # Specific provider implementations
│   └── services/           # Service layer unit tests
├── integration/            # Integration tests (multiple components/modules interaction)
└── e2e/                    # End-to-end tests (complete system flows - future)
```

## Test Categories

### Unit Tests
- Test individual functions, classes, or modules in isolation
- Use comprehensive mocking for external dependencies
- Fast execution with no external service requirements
- Mirror the `src/` directory structure for easy navigation

### Integration Tests  
- Test interaction between multiple components or modules
- May involve mocked external services but test internal integration points
- Validate system behavior across module boundaries
- Slightly slower than unit tests but still deterministic

### End-to-End Tests
- Test complete user flows or system behavior from end to end
- May require external services or live databases (not currently implemented)
- Slowest test category but provides highest confidence in system correctness

## Running Tests

### Proper Test Execution Protocol

For all testing activities, follow this protocol:
1. **Always use @Mr.Tester** for test execution, creation, and modification
2. **Never run tests manually** without involving @Mr.Tester
3. **Request structured reports** from @Mr.Tester for all test results

All tests can be run using pytest:

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
3. **End-to-End Tests**: Place in `tests/e2e/` when implemented

Use appropriate pytest markers if needed:
- `@pytest.mark.unit` for unit tests
- `@pytest.mark.integration` for integration tests  
- `@pytest.mark.e2e` for end-to-end tests

## Test Discovery

The pytest configuration in `pyproject.toml` automatically discovers tests in all subdirectories under `tests/`, so no additional configuration is needed when adding new test files.