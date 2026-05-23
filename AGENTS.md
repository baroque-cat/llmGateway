# llmGateway Development Guidelines

## Project Overview
llmGateway is a system for managing LLM provider API keys — background health monitoring (Keeper) and request routing through an API gateway (Conductor).

**Supported providers:** Anthropic (Claude), OpenAI-compatible (OpenAI, DeepSeek, Groq, etc.), Gemini.

The system consists of two independent components sharing the same codebase and database:
1. **Keeper** — background worker: health checks, key synchronization, database maintenance, key export.
2. **Conductor** (API Gateway) — FastAPI app: real-time request routing with key selection, retry policies, streaming, and debug modes.

## Running the Application
The project uses **Poetry** for dependency management and **Python 3.13**.

### Configuration
```bash
cp config/example_full_config.yaml config/providers.yaml
cp .env.example .env
# edit config/providers.yaml and .env
```
Config schema: Pydantic v2 models in `src/config/schemas.py`. Environment variables resolved from `.env` via `${ENV_VAR}` placeholders in YAML. See `docs/CONFIG_SYSTEM.md` for the full configuration subsystem architecture.

### Docker (recommended)
```bash
docker-compose up --build -d
```
Starts three services: PostgreSQL 18, Conductor (gateway on port 55300), Keeper.

### From source

```bash
# Install core + dev dependencies
poetry install --with dev
```

```bash
# Terminal 1 — API Gateway ("Conductor")
poetry run python main.py gateway --host 0.0.0.0 --port 55300

# Terminal 2 — Background worker ("Keeper")
poetry run python main.py keeper
```

## Architecture
```
src/
├── config/          # Configuration: Pydantic schemas, YAML loader, defaults, error formatting
├── core/            # Domain logic + abstractions (enums, interfaces, dataclasses, ConfigAccessor, probes, retry)
│   └── batching/    # AdaptiveBatchController (self-tuning batch size/delay)
├── db/              # Data access: PostgreSQL via raw asyncpg (no ORM), Repository pattern, connection pool
├── metrics/         # Observability: Prometheus (single + multiprocess) + in-memory backends
│   └── backends/    # Metrics backend implementations
├── providers/       # LLM adapters (Strategy + Template Method): AIBaseProvider → OpenAILike/Anthropic/Gemini
│   └── impl/        # Concrete provider implementations
└── services/        # Application orchestration
    ├── gateway/     # FastAPI app factory, dispatcher, in-memory key cache, response forwarding
    └── synchronizers/  # DB sync services (two-phase Read + Apply pattern)
```

**Key patterns:** Dependency Inversion (interfaces in `core/`), Facade (ConfigAccessor, DatabaseManager), Template Method (AIBaseProvider, IResourceProbe), Repository, Singleton (config, metrics), Two-Phase Apply-State Sync.

**Database:** PostgreSQL 18, 5 tables — `providers`, `proxies`, `provider_proxy_status`, `api_keys`, `key_model_status`. No ORM — raw `asyncpg` with connection pool.

## Code Style Guidelines
- **Modern Python**: Use Python 3.13+ features (union syntax `X | None`, not `Optional[X]`)
- **Asynchronous**: The architecture is fully asynchronous (`async`/`await`)
- **Strict Typing**: All function arguments and return values must have type hints. No bare generics — use `dict[str, int]`, not `dict`
- **Type checker**: pyright in strict mode (`typeCheckingMode: "strict"`, config: `pyrightconfig.json`). No mypy.
- **Linter**: ruff with rules E, F, W, I, B, C4, SIM, TID, UP, YTT. Run: `poetry run ruff check src/ tests/`
- **Formatter**: Black (line length 88, double quotes, 4 spaces). Run: `poetry run black src/ tests/`
- **Import style**: **Absolute imports only** — always `from src.module import Thing`, NEVER `from .module import Thing`. Enforced by ruff TID rule. Import order: stdlib → third-party → `src.*`
- **Naming Conventions**:
  - Variables/Functions/Methods: `snake_case`
  - Classes: `PascalCase`
  - Abstract classes / Interfaces: `I` prefix (`IProvider`, `IResourceSyncer`, `IMetricsCollector`)
  - Enums: `PascalCase` (`ErrorReason`, `Status`, `ProviderType`)
  - Constants: `UPPER_CASE` (`ALL_MODELS_MARKER`)
  - Private members: `_` prefix (`_refine_error_reason()`, `self._max_attempts`)
  - Test files/functions: `test_<snake_case>`
- **Documentation**: Google-style docstrings required for all public modules, classes, and functions. Sections: one-line summary, `Args:`, `Returns:`, `Raises:`, `Fields:` (for dataclasses). Sphinx cross-references allowed (`` :class:`~path.ClassName` ``).
- **Error Handling**: Use the `ErrorReason` enum from `src.core.constants` with its helper methods:
  - `is_fatal()` → `INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL` (immediate ban, no retry)
  - `is_retryable()` → `RATE_LIMITED`, `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `OVERLOADED`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT` (verification loop, then penalty)
  - `is_client_error()` → `BAD_REQUEST`, `UNKNOWN` (soft penalty only)
  - Full classification docs: `docs/ERRORS.md`

## Testing and Quality Assurance
All changes must pass testing and type checking.

### Test Structure
```
tests/
├── conftest.py          # Root: sets default env vars
├── unit/                # Unit tests (mirrors src/ structure)
│   ├── config/          # Config schema/loader validation
│   ├── core/            # Domain logic (constants, models, retry, probes, etc.)
│   ├── db/              # Database manager, repositories
│   ├── metrics/         # Metrics DTOs, backends, registry
│   ├── providers/       # Base provider, factory, error parsing
│   │   └── impl/        # Anthropic, OpenAI-like, Gemini adapters
│   └── services/        # Keeper, gateway, cache, probes, syncers
├── integration/         # Multi-component interaction tests
├── e2e/                 # End-to-end tests
├── security/            # Auth, credential sanitization, error security
└── test_batching/       # Adaptive batching tests
```

### Running Tests
For automated test execution and analysis, use the **@Mr.Tester** subagent, which is the recommended approach for running tests and generating structured QA reports.

The **@Mr.Tester** subagent will execute the test suite and provide detailed reports on test results, failures, and coverage. The main agent will then analyze these reports and determine the necessary actions.

```bash
# Run all tests
poetry run pytest

# Run a specific test file
poetry run pytest tests/path/to/test_file.py

# Run a specific test function
poetry run pytest tests/path/to/test_file.py::test_function_name

# Run with coverage
poetry run pytest --cov=src
```

### Test Conventions
- **Framework**: pytest ≥9.0 with `pytest-asyncio` and `pytest-cov`
- **Naming**: test files `test_<snake_case>.py`, test functions `test_<snake_case>`, test classes `class Test<Thing>:`
- **Async tests**: Always `@pytest.mark.asyncio` + `async def`. Strict async mode (no auto-detection).
- **Mocking**: `unittest.mock` only — `MagicMock`, `AsyncMock`, `patch`. Do NOT use `pytest-mock` (the `mocker` fixture is absent).
- **Fixtures**: Defined in `conftest.py` files or inline in test modules. Factory fixtures return callables for configurable setup.
- **No coverage thresholds** configured — coverage is informational.

### Type Checking
Always verify code type compliance with pyright in strict mode:
```bash
poetry run pyright
```
Config: `pyrightconfig.json` (strict mode, targets `src/`, `tests/`, `main.py`).

### Linting & Formatting
```bash
# Linting (ruff)
poetry run ruff check src/ tests/

# Formatting (Black, 88 chars, double quotes)
poetry run black src/ tests/
```

### CI Pipeline
`.github/workflows/quality.yml` runs on every push: pyright → ruff check → black --check → pytest --cov=src → codecov. All steps must pass.

## Documentation

The `docs/` directory contains detailed subsystem documentation. Consult these files alongside the source code for architectural context and design rationale:

| Document | Topic |
| --- | --- |
| `docs/CONFIG_SYSTEM.md` | Configuration subsystem: three-tier defaults, two-pass env var resolution, Pydantic model hierarchy, loader flow, public API |
| `docs/ERRORS.md` | ErrorReason enum classification: fatal vs retryable vs client errors, key penalty logic |
| `docs/ERROR_PARSING.md` | Pattern-based error reclassification: rules, priority system, dual-format providers |
| `docs/DEBUG_MODE.md` | Gateway debug modes: `disabled`, `no_content`, `full_body` |

**Primary config reference:** `config/example_full_config.yaml` — annotated example covering every available setting with inline documentation.
