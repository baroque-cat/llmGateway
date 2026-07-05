# llmGateway Development Guidelines — Code Paradigm & Practices

## Project Overview

llmGateway is a system for managing LLM provider API keys — background health
monitoring (Keeper) and request routing through an API gateway (Conductor).

**Supported providers:** Anthropic (Claude), OpenAI-compatible (OpenAI, DeepSeek,
Groq, etc.), Gemini.

Two independent components share the same codebase and database:

1. **Keeper** — background worker: health checks, key synchronization, database
   maintenance, key export.
2. **Conductor** (API Gateway) — FastAPI app: real-time request routing with key
   selection, retry policies, streaming, and debug modes.

## Technology Stack

- **Language**: Python ≥3.13.5, fully asynchronous (`async`/`await`)
- **Package manager**: Poetry (development), uv (Docker builds)
- **Web framework**: FastAPI ≥0.120 + Uvicorn ASGI server
- **Database**: PostgreSQL 18 via raw `asyncpg` (no ORM), connection pool pattern
- **LLM providers**: No SDKs — raw `httpx` HTTP/2 calls to upstream APIs
- **Scheduler**: APScheduler `AsyncIOScheduler` (Keeper background jobs)
- **Configuration**: Pydantic v2 schema validation, YAML loader with two-pass
  `${ENV_VAR}` resolution and three-tier default merge
- **Metrics**: `prometheus-client`, pluggable backends (Prometheus single/multiprocess
  + in-memory for testing)
- **Containerization**: Docker Compose — PostgreSQL 18 + Keeper + Conductor

## Architecture

```
src/
├── config/          # Configuration: Pydantic schemas, YAML loader, defaults, error formatting
├── core/            # Domain logic + abstractions (enums, interfaces, dataclasses, ConfigAccessor, probes, retry)
│   ├── batching/    # AdaptiveBatchController (self-tuning batch size/delay)
│   └── http2/       # Custom HTTP/2 transport (capacity-aware connection pool)
├── db/              # Data access: PostgreSQL via raw asyncpg (no ORM), Repository pattern
├── metrics/         # Observability: Prometheus (single + multiprocess) + in-memory backends
│   └── backends/    # Metrics backend implementations
├── providers/       # LLM adapters (Strategy + Template Method): AIBaseProvider → OpenAILike/Anthropic/Gemini
│   └── impl/        # Concrete provider implementations
└── services/        # Application orchestration
    ├── gateway/     # FastAPI app factory, in-memory key cache, response forwarding, content sanitization
    └── synchronizers/  # DB sync services (Two-Phase Read + Apply pattern)
```

**Key design patterns:**

| Pattern | Where | Role |
| --- | --- | --- |
| Dependency Inversion | `core/interfaces.py` → outer layers | All `I`-prefixed ABCs (`IProvider`, `IResourceSyncer`, `IResourceProbe`, `IMetricsCollector`) live in `core/`. Outer layers implement them. |
| Facade | `ConfigAccessor`, `DatabaseManager` | Typed read-only wrappers over nested config trees and repository collections |
| Template Method | `AIBaseProvider`, `IResourceProbe` | Base declares algorithm skeleton; subclasses fill abstract steps |
| Strategy | `providers/impl/` | `OpenAILikeProvider`, `AnthropicProvider`, `GeminiProvider` — interchangeable via factory |
| Repository | `KeyRepository`, `ProviderRepository`, `ProxyRepository` | Raw SQL queries, typed results via `TypedDict`, no ORM |
| Singleton | Config, metrics collector, DB pool | Module-level state with `get_*()` accessors |
| Two-Phase Apply-State | `services/synchronizers/` | Phase 1: Read desired state from files/config. Phase 2: Apply to DB polymorphically. |

**Database:** PostgreSQL 18, 5 tables — `providers`, `proxies`,
`provider_proxy_status`, `api_keys`, `key_model_status`. No ORM — raw `asyncpg`
with connection pool.

## Code Style Guidelines

### Language Features

- **Modern Python 3.13+**: union syntax `X | None`, never `Optional[X]`
- **Fully asynchronous**: `async`/`await` throughout; all I/O is non-blocking
- **`from __future__ import annotations`** for forward-reference types where needed
- **No bare generics**: always `dict[str, int]`, `list[str]`, never `dict`, `list`
- **`StrEnum`** for string-valued enums (from `enum`)

### Strict Typing

- **Type checker**: pyright. `typeCheckingMode: "basic"` globally, **strict mode**
  only on `src/core/` and `src/config/` (see `pyrightconfig.json`). No mypy.
- **All function arguments and return values** must have type hints.
- **`TYPE_CHECKING` guard** in `core/interfaces.py` to prevent runtime circular imports
  from `db/` or `services/`.
- **TypedDict** for structured dict shapes (query results, cache entries).
- **`@dataclass(frozen=True)`** for immutable DTOs; mutable only where mutation is required.
- `# pyright: ignore[...]` pragmas allowed for runtime/mock edge cases.

### Linting & Formatting

- **Linter**: ruff — rules `E`, `F`, `W`, `I`, `B`, `C4`, `SIM`, `TID`, `UP`, `YTT`.
  `E501` (line too long) ignored — delegated to formatter.
- **Formatter**: Black — line length 88, double quotes, 4-space indentation.
  Ruff format as compatible alternative.
- **isort**: enforced by ruff `I` + `TID` rules. Groups: stdlib → third-party → `src.*`.

### Naming Conventions

| Category | Convention | Examples |
| --- | --- | --- |
| Variables / Functions / Methods | `snake_case` | `is_fatal()`, `get_keys_to_check()` |
| Classes | `PascalCase` | `CheckResult`, `DatabaseManager` |
| Abstract classes / Interfaces | `I` prefix | `IProvider`, `IResourceSyncer`, `IMetricsCollector` |
| Enums | `PascalCase`, `@unique` | `ErrorReason`, `Status`, `ProviderType` |
| Constants | `UPPER_CASE` | `ALL_MODELS_MARKER`, `DB_SCHEMA` |
| Private members | `_` prefix | `_refine_error_reason()`, `self._pool` |
| Test files | `test_<snake_case>.py` | `test_retry.py`, `test_gemini.py` |
| Test classes | `class Test<Thing>:` | `class TestGeminiErrorParsing:` |
| Test functions | `test_<snake_case>` | `test_success_on_first_attempt()` |

### Imports

- **Absolute imports only**: always `from src.module import Thing`, **never**
  `from .module import Thing`. Enforced by ruff `TID` rule.
- **Import order**: stdlib → third-party → `src.*` (enforced by isort).
- `TYPE_CHECKING` guard used in `core/interfaces.py` to break circular dependency
  with `db/` at runtime.

### Documentation

- **Google-style docstrings** required for all public modules, classes, functions.
- Sections: one-line summary, `Args:`, `Returns:`, `Raises:`, `Fields:` (dataclasses),
  `Attributes:` (exception classes).
- Sphinx cross-references: `` :class:`~path.ClassName` `` (double-backtick syntax).
- Module-level docstrings for all `.py` files.

### Error Handling

Use the `ErrorReason` enum from `src.core.constants` — the single source of truth
for all upstream error classification:

| Category | Values | Behavior |
| --- | --- | --- |
| `is_fatal()` | `INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL` | Immediate ban, no retry |
| `is_retryable()` | `RATE_LIMITED`, `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `OVERLOADED`, `SERVICE_UNAVAILABLE`, `STREAM_DISCONNECT` | Verification loop (up to 3 retries with delay), then penalty |
| `is_client_error()` | `BAD_REQUEST`, `UNKNOWN` | Soft penalty only (1 hour) |
| `is_server_error()` | Subset of retryable | Provider-infrastructure issues vs key-specific |

Full classification: `docs/ERRORS.md`. Error parsing rules: `docs/ERROR_PARSING.md`.

### Logging

- Module-level `logger = logging.getLogger(__name__)` in every module.
- f-strings for log messages; `exc_info=True` for exception logging.
- httpx trace logging available via `src/config/logging_config.py`.

## Testing

> **Primary testing documentation:** [TESTING.md](TESTING.md) — index of all testing docs.
> For conventions and the Golden Rule, see [TESTING-GUIDE.md](TESTING-GUIDE.md).
> For how to run tests, see [TESTING-RUN.md](TESTING-RUN.md).
> For the zero-hardcodes gatekeeper, see [TESTING-GATEKEEPER.md](TESTING-GATEKEEPER.md).

### Quick Reference

- **Framework**: pytest ≥9.0 + pytest-asyncio (strict mode) + pytest-cov
- **Async tests**: always `@pytest.mark.asyncio` + `async def`, no auto-detection
- **Mocking**: `unittest.mock` only (`AsyncMock`, `MagicMock`, `patch`). **Do NOT**
  use `pytest-mock` / `mocker` fixture — it is intentionally absent.
- **Golden Rule**: all configuration values in tests must derive from `CanonicalConfig`
  (see [TESTING-GUIDE.md](TESTING-GUIDE.md)). Zero hardcodes.
- **Test structure**: `tests/unit/` (mirrors `src/`), `tests/integration/`,
  `tests/e2e/`, `tests/security/`, `tests/batching/`, `tests/stress/`.
- **Markers**: `slow` (real HTTP/2), `postgres` (live DB), `meta` (structural integrity).
- **No coverage thresholds** — coverage is informational only.

### Quality Gates

All changes must pass:

| Gate | Tool | Command |
| --- | --- | --- |
| Type check | pyright (strict on `src/core`, `src/config`) | `poetry run pyright` |
| Lint | ruff (E, F, W, I, B, C4, SIM, TID, UP, YTT) | `poetry run ruff check src/ tests/` |
| Format | black (88 chars, double quotes) | `poetry run black --check src/ tests/` |
| Tests | pytest (G1–G5) | `make test` |
| Hardcodes | Gatekeeper script | `bash scripts/check-test-hardcodes.sh all` |
| CI | GitHub Actions `quality.yml` | `make ci` |

## Documentation

The `docs/` directory contains subsystem reference documentation:

| Document | Topic |
| --- | --- |
| `docs/CONFIG_SYSTEM.md` | Configuration subsystem: three-tier defaults, two-pass `${ENV_VAR}` resolution, Pydantic model hierarchy, public API |
| `docs/ERRORS.md` | `ErrorReason` enum classification: fatal vs retryable vs client errors, key penalty logic |
| `docs/ERROR_PARSING.md` | Pattern-based error reclassification: rules, priority system, dual-format providers |
| `docs/DEBUG_MODE.md` | Gateway debug modes: `disabled`, `no_content`, `full_body` |
| `docs/HTTP2_STRESS_TESTS.md` | HTTP/2 stress test design and analysis |
| `docs/THROUGHPUT_BOTTLENECK_PROBLEM.md` | Known throughput bottleneck investigation |
| `docs/CASCADING_FREEZE_EVIDENCE.md` | Evidence of cascading freeze problems under HTTP/2 concurrency limits |

**Testing documentation** (project root):

| Document | Audience | Content |
| --- | --- | --- |
| `TESTING.md` | Everyone | Single entry point, index, quick start |
| `TESTING-GUIDE.md` | Test authors | Golden Rule, CanonicalConfig, boundary annotations, anti-patterns |
| `TESTING-RUN.md` | Developers, CI | Makefile targets, process-isolation groups (G1–G6), timeout policy, markers |
| `TESTING-GATEKEEPER.md` | Maintainers | Zero-hardcodes enforcement: script architecture, banned patterns, cache fixtures |

**Primary config reference:** `config/example_full_config.yaml` — annotated example
covering every available setting with inline documentation.
