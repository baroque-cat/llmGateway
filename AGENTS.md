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

## 4. Git & Commit Protocol
- **Atomic Commits**: Group related changes.
- **Message Format**: `<type>: <description>` (e.g., `feat: add deepseek provider`, `fix: correct retry logic`).
- **Safety**: Do not commit secrets (API keys, .env files).

## 5. Agent Behavior
- **Analyze First**: Read related files before modifying.
- **Incremental Changes**: Make small, verifiable changes.
- **Verify**: Run `pytest` after implementation.
- **Match Context**: Adopt the style of the file you are editing.
