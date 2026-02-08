# llmGateway Development Guidelines

## Project Overview
llmGateway is a system for managing LLM provider API keys with background monitoring of their status and request distribution through a gateway.

## Running the Application
The project uses **Poetry** for dependency management and **Python 3.13**.

### Installation
```bash
# Install core dependencies
poetry install

# Install development dependencies
poetry install --with dev
```

### Running
```bash
# Run the background worker ("Keeper")
poetry run python main.py worker

# Run the API Gateway ("Conductor")
poetry run python main.py gateway
```

## Code Style Guidelines
- **Modern Python**: Use Python 3.13+ features
- **Asynchronous**: The architecture is fully asynchronous (`async`/`await`)
- **Strict Typing**: All function arguments and return values must have type hints
- **Naming Conventions**:
  - Variables/Functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_CASE`
  - Private members: `_prefix`
- **Documentation**: Docstrings are required for all public modules, classes, and functions
- **Error Handling**: Use typed exceptions and enums from `src.core.constants.ErrorReason`

## Testing and Quality Assurance
All changes must pass testing and type checking:

### Testing
Tests are located in the `tests/` directory. Always run tests to verify changes. For automated test execution and analysis, use the **@Mr.Tester** subagent, which is the recommended approach for running tests and generating structured QA reports.

The **@Mr.Tester** subagent will execute the test suite and provide detailed reports on test results, failures, and coverage. The main agent will then analyze these reports and determine the necessary actions.

```bash
# Run all tests
poetry run pytest

# Run a specific test file
poetry run pytest tests/path/to/test_file.py

# Run a specific test function
poetry run pytest tests/path/to/test_file.py::test_function_name
```

### Type Checking
Always verify code type compliance with pyright:
```bash
# Type checking
poetry run pyright
```

### Additional Tools
```bash
# Linting
poetry run ruff check src/ tests/

# Formatting
poetry run black src/ tests/
```