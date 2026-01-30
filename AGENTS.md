# Agent Guidelines for llmGateway

This document defines the development standards, commands, and rules for AI agents operating in this codebase.

## 1. Environment & Commands

The project uses **Poetry** for dependency management and **Python 3.13**.

### Setup & Installation
```bash
# Install dependencies
poetry install
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

#### Error Parsing Testing
The project includes comprehensive tests for error parsing functionality. These tests ensure that 400 errors with different meanings (e.g., Qwen's "Arrearage" errors vs format errors) are correctly classified.

**Test Files:**
- `tests/test_error_parsing_validation.py` - Configuration validation tests
- `tests/test_error_parsing_base.py` - Base provider logic tests  
- `tests/test_error_parsing_openai_like.py` - OpenAI-like provider integration tests
- `tests/test_error_parsing_gemini.py` - Gemini provider integration tests
- `tests/test_error_parsing_scenarios.py` - End-to-end scenario tests
- `tests/test_error_parsing_edge_cases.py` - Edge case and performance tests

**Running Error Parsing Tests:**
```bash
# Run all error parsing tests
poetry run pytest tests/test_error_parsing*.py

# Run specific test categories
poetry run pytest tests/test_error_parsing_scenarios.py -v
```

**Example Test Scenario:**
```python
# Testing Qwen "Arrearage" error mapping
async def test_qwen_arrearage_scenario(self):
    provider = create_mock_openai_provider(
        error_config=ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="Arrearage|BillingHardLimit",
                    map_to="invalid_key",
                    priority=10
                )
            ]
        )
    )
    # Mock 400 response with Arrearage error
    result = await provider._parse_proxy_error(mock_response)
    assert result.error_reason == ErrorReason.INVALID_KEY
```

### Linting & Formatting
Currently, the project does not enforce strict linter configuration in `pyproject.toml`. Agents should strive to match existing code style:
- **Format**: Follow standard PEP 8 (4 spaces indent).
- **Imports**: Sort imports (Standard lib -> Third party -> Local). Use absolute imports (e.g., `from src.core.models import ...`).

## 2. Code Style Guidelines

### General Philosophy
- **Modern Python**: Use Python 3.13+ features.
- **Async First**: The architecture is fundamentally asynchronous (`async`/`await`). Use `httpx` for requests, `asyncpg` for DB.
- **Type Safety**: Strong typing is mandatory.

### Type Hinting
- **Strict Typing**: All function arguments and return values MUST have type hints.
- Use `typing.Optional`, `typing.List`, `typing.Dict`, `typing.Any` (sparingly).
- Use `dataclasses` for data structures.

```python
# GOOD
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserConfig:
    user_id: int
    name: str
    is_active: bool = True

async def fetch_user(user_id: int) -> Optional[UserConfig]:
    ...
```

### Naming Conventions
- **Variables/Functions**: `snake_case` (e.g., `fetch_data`, `user_id`)
- **Classes**: `PascalCase` (e.g., `GatewayService`, `check_result`)
- **Constants**: `UPPER_CASE` (e.g., `MAX_RETRIES`, `DEFAULT_TIMEOUT`)
- **Private Members**: Prefix with underscore `_` (e.g., `_internal_cache`)

### Documentation
- **Docstrings**: Required for all public modules, classes, and functions.
- **Style**: Use a summary line, followed by a blank line, then a detailed description.
- **Arguments**: Document complex arguments if not obvious from type hints.

```python
def parse_request(data: dict) -> RequestDetails:
    """
    Parses raw request data into a structured object.

    This ensures the gateway can handle the request in a standardized way
    regardless of the input format.
    """
    ...
```

### Error Handling
- **Typed Exceptions**: Use custom exceptions or specific standard exceptions. Avoid bare `except Exception:`.
- **Enums**: Use `src.core.enums.ErrorReason` for standardized error reporting in `CheckResult`.
- **Fail Gracefully**: The system is designed for high availability. One failure should not crash the worker.

### Architecture Patterns
- **Factory Pattern**: Used for creating providers and clients (e.g., `HttpClientFactory`).
- **Facade**: `accessor.py` provides a clean interface to configuration.
- **Dependency Injection**: Pass dependencies (like DB pools or Config objects) into services/providers rather than using global state.

## 3. Project Structure
- `src/config`: Configuration logic (loader, schemas, validator).
- `src/core`: Core abstractions, interfaces, and shared models.
- `src/db`: Database interaction layer (`asyncpg`).
- `src/providers`: External API integration logic.
- `src/services`: Business logic (worker, gateway, stats).

## 4. Streaming Configuration

The gateway service supports manual control over streaming behavior through configuration:

### Global Configuration
In the root of your `providers.yaml` file, you can set a global streaming mode:
```yaml
gateway:
  streaming_mode: "auto" # or "disabled"
```

### Provider-Specific Configuration  
In each provider's `gateway_policy` section, you can override the global setting:
```yaml
providers:
  my_provider:
    gateway_policy:
      streaming_mode: "auto" # or "disabled"
```

### Streaming Modes
- **`auto`**: Streaming is enabled when technically possible (current default behavior).
- **`disabled`**: Streaming is explicitly disabled in both directions (request and response) for debugging or special requirements.

### Priority Logic
Provider-specific settings take precedence over global settings. If a provider's `streaming_mode` is set to `"auto"`, it will inherit the global setting.

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
        require_buffering: false
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
- **map_to**: ErrorReason enum value (see `src.core.enums.ErrorReason`)
- **priority**: Higher priority rules win when multiple rules match (default: 0)
- **description**: Optional human-readable description

### Example Scenarios
1. **Qwen "Arrearage" errors**: Map 400 with error.type="Arrearage" to INVALID_KEY
2. **OpenAI quota errors**: Map 400 with error.code="insufficient_quota" to NO_QUOTA
3. **Gemini authentication**: Map 400 with error.status="INVALID_ARGUMENT" to INVALID_KEY

### Priority System
When multiple rules match, the highest priority rule determines the error mapping. This allows fine-grained control over error classification.

### Default Behavior
When error parsing is disabled (`enabled: false`) or no rules match, the system falls back to provider-specific HTTP status code mapping.

## 6. Git & Commit Protocol
- **Atomic Commits**: Group related changes.
- **Message Format**: `<type>: <description>` (e.g., `feat: add deepseek provider`, `fix: correct retry logic`).
- **Safety**: Do not commit secrets (API keys, .env files).

## 7. Agent Behavior
- **Analyze First**: Read related files before modifying.
- **Incremental Changes**: Make small, verifiable changes.
- **Verify**: Run `pytest` after implementation.
- **Match Context**: Adopt the style of the file you are editing.
