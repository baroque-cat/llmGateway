# Agent Guidelines for llmGateway

This document defines the development standards, commands, and rules for AI agents operating in this codebase.

## 1. Environment & Commands

The project uses **Poetry** for dependency management and **Python 3.13**.

### Setup & Installation
```bash
# Install dependencies
poetry install

# Install development dependencies (for linting, type checking, etc.)
poetry install --with dev
```

### Running the Application
The application has two main modes: Worker and Gateway (future).
```bash
# Run the Background Worker ("Хранитель")
poetry run python main.py worker

# Run Configuration CLI
poetry run python main.py config create <type>:<name>
```

### Testing
**Critical**: Always run tests to verify changes.
```bash
# Run all tests
poetry run pytest

# Run a specific test file
poetry run pytest tests/path/to/test_file.py

# Run a specific test function
poetry run pytest tests/path/to/test_file.py::test_function_name

# Run with verbose output (useful for debugging)
poetry run pytest -v
```

### Development Tools
The project includes comprehensive development tooling for code quality:

#### Type Checking
```bash
# Run mypy type checking
poetry run mypy src/ --strict
```

#### Linting
```bash
# Run ruff linting
poetry run ruff check src/ tests/

# Auto-fix linting issues
poetry run ruff check src/ tests/ --fix
```

#### Formatting
```bash
# Check formatting with black
poetry run black --check src/ tests/

# Auto-format code
poetry run black src/ tests/
```

#### Code Coverage
```bash
# Run tests with coverage report
poetry run pytest --cov=src --cov-report=term-missing
```

## 2. Code Style Guidelines

### General Philosophy
- **Modern Python**: Use Python 3.13+ features.
- **Async First**: The architecture is fundamentally asynchronous (`async`/`await`). Use `httpx` for requests, `asyncpg` for DB.
- **Type Safety**: Strong typing is mandatory.

### Type Hinting
- **Strict Typing**: All function arguments and return values MUST have type hints.
- Use `typing.Optional`, `typing.List`, `typing.Dict`, `typing.Any` (sparingly).
- Use `dataclasses` for data structures.

### Naming Conventions
- **Variables/Functions**: `snake_case` (e.g., `fetch_data`, `user_id`)
- **Classes**: `PascalCase` (e.g., `GatewayService`, `check_result`)
- **Constants**: `UPPER_CASE` (e.g., `MAX_RETRIES`, `DEFAULT_TIMEOUT`)
- **Private Members**: Prefix with underscore `_` (e.g., `_internal_cache`)

### Documentation
- **Docstrings**: Required for all public modules, classes, and functions.
- **Style**: Use a summary line, followed by a blank line, then a detailed description.

### Error Handling
- **Typed Exceptions**: Use custom exceptions or specific standard exceptions. Avoid bare `except Exception:`.
- **Enums**: Use `src.core.constants.ErrorReason` for standardized error reporting in `CheckResult`.
- **Fail Gracefully**: The system is designed for high availability. One failure should not crash the worker.

## 3. Project Structure
- `src/config`: Configuration logic (loader, schemas, validator).
- `src/core`: Core abstractions, interfaces, and shared models.
- `src/db`: Database interaction layer (`asyncpg`).
- `src/providers`: External API integration logic.
- `src/services`: Business logic (worker, gateway, stats).

## 4. Streaming Configuration

The gateway service supports manual control over streaming behavior through configuration:

### Provider-Specific Configuration  
In each provider's `gateway_policy` section, you can set the streaming mode:
```yaml
providers:
  my_provider:
    gateway_policy:
      streaming_mode: "auto" # or "disabled"
```

### Streaming Modes
- **`auto`**: Streaming is enabled when technically possible (current default behavior).
- **`disabled`**: Streaming is explicitly disabled in both directions (request and response) for debugging or special requirements.

## 5. Error Parsing Configuration

The gateway service includes sophisticated error parsing to distinguish between different types of HTTP errors (e.g., authentication errors vs quota errors vs bad requests). This is particularly important for 400 errors which can have different meanings across providers.

### Configuration Structure
Error parsing is configured in each provider's `gateway_policy` section:

```yaml
providers:
  my_provider:
    gateway_policy:
      error_parsing:
        enabled: true
        rules:
          - status_code: 400
            error_path: "error.type"
            match_pattern: "Arrearage|BillingHardLimit"
            map_to: "invalid_key"
            priority: 10
            description: "Payment overdue or billing limit"
          - status_code: 400
            error_path: "error.code"
            match_pattern: "insufficient_quota"
            map_to: "no_quota"
            priority: 5
            description: "Insufficient quota or credits"
```

### Rule Fields
- **status_code**: HTTP status code to match (e.g., 400, 429)
- **error_path**: Dot-separated JSON path to extract error details (e.g., "error.type", "error.code")
- **match_pattern**: Regex pattern to match against the extracted value
- **map_to**: ErrorReason enum value (see `src.core.constants.ErrorReason`)
- **priority**: Higher priority rules win when multiple rules match (default: 0)
- **description**: Optional human-readable description

### Priority System
When multiple rules match, the highest priority rule determines the error mapping. This allows fine-grained control over error classification.

## 6. Git & Commit Protocol
- **Atomic Commits**: Group related changes.
- **Message Format**: `<type>: <description>` (e.g., `feat: add deepseek provider`, `fix: correct retry logic`).
- **Safety**: Do not commit secrets (API keys, .env files).

## 7. Agent Behavior
- **Analyze First**: Read related files before modifying.
- **Incremental Changes**: Make small, verifiable changes.
- **Verify**: Run `pytest` after implementation.
- **Match Context**: Adopt the style of the file you are editing.

## 8. Configuration System Architecture

The project employs a robust, type-safe configuration system located in `src/config/` with a facade in `src/core/accessor.py`.

### Components Overview

1. **Schemas (`src/config/schemas.py`)**
   - **Role**: Defines the configuration data models using Python `dataclasses`.
   - **Details**: Provides strict type hinting for all configuration options (Database, Worker, Providers, Policies). It ensures that the configuration structure is well-defined and predictable for IDEs and static analysis.

2. **Loader (`src/config/loader.py`)**
   - **Role**: Handles the loading lifecycle: YAML reading -> Env Var Resolution -> Merging -> Object Instantiation.
   - **Workflow**:
     1. Reads `config/providers.yaml`.
     2. Resolves `${VAR_NAME}` placeholders using environment variables.
     3. Merges user config with `src/config/defaults.py` to ensure all fields exist.
     4. Converts the resulting dictionary into nested `dataclass` objects.

3. **Validator (`src/config/validator.py`)**
   - **Role**: Enforces business logic and integrity checks on the loaded configuration.
   - **Details**: Runs after loading. Checks for logical errors (e.g., negative timeouts, invalid modes, missing keys) and accumulates all errors into a single report to guide the user in fixing them.

4. **Defaults (`src/config/defaults.py`)**
   - **Role**: Provides the "Source of Truth" for default values.
   - **Details**: Returns a dictionary that acts as a base for the merge process, ensuring that even if a user omits optional sections, the application receives valid default settings.

5. **Accessor (`src/core/accessor.py`)**
   - **Role**: The public API (Facade) for accessing configuration data.
   - **Details**:
     - Decouples the rest of the application (Worker, Gateway) from the internal structure of `src/config`.
     - Provides safe "getter" methods (e.g., `get_provider(name)`) that handle potential `None` values or lookups.
     - **Rule**: Application code should NEVER import `Config` directly; it should always use `ConfigAccessor`.

## 9. Shared Key Optimization Implementation

### Completed Work Summary
The shared key optimization refactoring has been successfully implemented using a "Virtual Model" pattern. Key achievements include:

1. **Reduced Database Redundancy**: When `shared_key_status=True`, only one row per key is stored instead of one per model, significantly reducing database size.

2. **Optimized Cache Usage**: Shared keys are stored in a single virtual pool (`provider:__ALL_MODELS__`) instead of being duplicated across all model pools.

3. **Efficient Worker Checks**: The background worker only checks one model per key for shared providers, saving resources while maintaining proper health monitoring.

4. **Backward Compatibility**: Normal (non-shared) keys continue to work exactly as before with no changes required.

5. **Proper Error Handling**: Failed shared keys are correctly removed from the virtual pool and status updates target the correct `__ALL_MODELS__` marker.

### Implementation Details
- **Constants**: Added `ALL_MODELS_MARKER = "__ALL_MODELS__"` in `src/core/constants.py`
- **Database Layer**: Updated `KeyRepository` methods to handle virtual model pattern
- **Gateway Cache**: Modified cache logic to use virtual pools for shared keys
- **Worker Probe**: Enhanced to resolve real models for API calls while using virtual markers for status updates
- **Testing**: Added verification tests and confirmed all existing tests pass

This optimization is particularly beneficial for providers with account-level rate limits or shared key status, where all models share the same key validity state.