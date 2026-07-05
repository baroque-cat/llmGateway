# llmGateway

API gateway for managing LLM provider keys — health monitoring, request routing, and retry.

**Supported providers:**
- **Anthropic** — Claude API
- **OpenAI-compatible** — OpenAI, DeepSeek, Groq, and any OpenAI-compatible API
- **Gemini** — Google Gemini API

The system consists of two independent components:

1. **Keeper** — background service for health checks, key synchronization, database maintenance, and key export.
2. **Conductor** (API Gateway) — real-time request routing with key selection, retry policies, streaming, and debug modes.

## Technology Stack

| Component | Version |
| --- | --- |
| Python | ≥3.13.5 |
| FastAPI | ≥0.120 |
| PostgreSQL | 18 (Alpine) |
| Pydantic | v2 |
| asyncpg | ≥0.30 (raw, no ORM) |
| httpx | ≥0.28 (HTTP/2) |
| pytest | ≥9.0 |
| Package manager | Poetry (dev), uv (Docker) |

## Quick Start

### Docker (recommended)

```bash
cp config/example_full_config.yaml config/providers.yaml
cp .env.example .env
# edit config/providers.yaml and .env
docker-compose up --build -d
```

Starts three services: PostgreSQL 18, Conductor (gateway on port 55300), Keeper.

### From source

```bash
poetry install --with dev
cp config/example_minimal_config.yaml config/providers.yaml
# edit config/providers.yaml

# Terminal 1 — Gateway
poetry run python main.py gateway --host 0.0.0.0 --port 55300

# Terminal 2 — Keeper
poetry run python main.py keeper
```

Prerequisites: Python 3.13+, Poetry, PostgreSQL.

## Configuration

`config/providers.yaml` is the single configuration file. Schema: `src/config/schemas.py`.

Key concepts:
- **Providers** — LLM API adapters (OpenAI-compatible, Anthropic, Gemini)
- **Health Policy** — per-provider check intervals, quarantine, key purge
- **Error Parsing** — regex-based error classification from response bodies
- **Adaptive Batching** — self-tuning batch controller for health probes
- **Retry Policy** — gateway-side retry with key rotation and backoff
- **Key Export** — periodic NDJSON snapshots and status inventory

Example configs: `config/example_full_config.yaml`, `config/example_minimal_config.yaml`.

## Directory Structure

```
llmGateway/
├── .github/
│   └── workflows/
│       └── quality.yml              # CI: pyright → ruff → black → pytest → codecov
├── config/
│   ├── example_full_config.yaml     # All available options with inline docs
│   └── example_minimal_config.yaml  # Quick-start template
├── data/                            # Key files per provider (.txt / .ndjson)
├── docs/
│   ├── CONFIG_SYSTEM.md             # Configuration subsystem architecture
│   ├── ERRORS.md                    # ErrorReason classification catalog
│   ├── ERROR_PARSING.md             # Regex-based error reclassification
│   ├── DEBUG_MODE.md                # Debug modes: disabled, no_content, full_body
│   ├── HTTP2_STRESS_TESTS.md        # HTTP/2 stress test design
│   ├── THROUGHPUT_BOTTLENECK_PROBLEM.md
│   └── CASCADING_FREEZE_EVIDENCE.md
├── examples/
├── openspec/                        # Specification documents
├── scripts/
├── src/
│   ├── config/                      # Configuration subsystem
│   │   ├── __init__.py              # load_config(), get_config() (singleton)
│   │   ├── schemas.py               # Pydantic v2 config model hierarchy
│   │   ├── loader.py                # YAML loader + two-pass ${ENV_VAR} resolution
│   │   ├── defaults.py              # Three-tier default values
│   │   ├── error_formatter.py       # Human-readable validation error formatting
│   │   └── logging_config.py        # setup_logging(), httpx trace handler
│   ├── core/                        # Domain logic & abstractions (the "kernel")
│   │   ├── constants.py             # Enums: ErrorReason, Status, DebugMode, ProviderType
│   │   ├── interfaces.py            # ABCs: IProvider, IResourceSyncer, IResourceProbe, IMetricsCollector
│   │   ├── models.py                # DTOs: CheckResult, RequestDetails, DatabaseTableHealth
│   │   ├── accessor.py              # ConfigAccessor — typed read-only config facade
│   │   ├── probes.py                # IResourceProbe template + AdaptiveBatchController dispatch
│   │   ├── retry.py                 # AsyncRetrier with exponential backoff + jitter
│   │   ├── http_client_factory.py   # Long-lived httpx.AsyncClient per provider
│   │   ├── policy_utils.py          # compute_next_check_time()
│   │   ├── atomic_io.py             # Atomic NDJSON file writes
│   │   ├── exception_handler.py     # @handle_exceptions decorator
│   │   ├── batching/
│   │   │   └── adaptive.py          # Self-tuning batch controller (3-priority algorithm)
│   │   └── http2/                   # Custom HTTP/2 transport
│   │       ├── transport.py         # CapacityAwareHttp2Transport
│   │       ├── connection.py        # Connection lifecycle
│   │       ├── pool.py              # Connection pool
│   │       └── semaphore.py         # Stream concurrency control
│   ├── db/
│   │   └── database.py              # PostgreSQL: connection pool, schema, repositories, DatabaseManager
│   ├── metrics/                     # Observability
│   │   ├── __init__.py              # get_collector(), reset_collector() (singleton)
│   │   ├── registry.py              # Metric name constants
│   │   ├── contracts.py             # GaugeSpec, MetricValue dataclasses
│   │   ├── auth.py                  # Bearer-token validation for /metrics endpoint
│   │   └── backends/
│   │       ├── prometheus.py        # PrometheusMetricsCollector (production)
│   │       └── memory.py            # MemoryMetricsCollector (testing)
│   ├── providers/                   # LLM adapters (Strategy + Template Method)
│   │   ├── __init__.py              # get_provider() factory + _PROVIDER_CLASSES registry
│   │   ├── base.py                  # AIBaseProvider — shared proxy + error parsing pipeline
│   │   └── impl/
│   │       ├── openai_like.py       # OpenAI-compatible APIs
│   │       ├── anthropic.py         # Anthropic (Claude) API
│   │       ├── gemini.py            # Google Gemini provider
│   │       └── gemini_base.py       # Gemini shared check/error-mapping
│   └── services/                    # Application orchestration
│       ├── gateway/                 # Conductor — FastAPI API Gateway
│       │   ├── gateway_service.py   # Routing, retry, streaming, debug modes
│       │   ├── gateway_cache.py     # In-memory key pool + auth token cache
│       │   ├── response_forwarder.py  # Upstream response lifecycle
│       │   └── sanitize_content.py  # Debug-mode content redaction
│       ├── synchronizers/           # DB sync (Two-Phase Read + Apply)
│       │   └── key_sync.py          # KeySyncer: NDJSON files → PostgreSQL
│       ├── keeper.py                # Keeper entry point: APScheduler + health cycles
│       ├── key_probe.py             # Per-key health probing
│       ├── key_purger.py            # Stopped key cleanup
│       ├── db_maintainer.py         # Conditional VACUUM ANALYZE
│       └── inventory_exporter.py    # NDJSON snapshot + status inventory export
├── tests/                           # ~200 test files
│   ├── _canonical.py                # CanonicalConfig — single source of config truth
│   ├── _constants.py                # Shared mock token constants
│   ├── conftest.py                  # Global fixtures (env setup, gatekeeper cache)
│   ├── test_*.py                    # Root-level gatekeeper tests (G5, ~30 files)
│   ├── unit/                        # Unit tests (G1 + G2), mirrors src/ structure
│   │   └── {config,core,db,metrics,providers,services}/
│   ├── integration/                 # Integration tests (G3)
│   ├── security/                    # Security tests (G3)
│   ├── e2e/                         # End-to-end tests (G3)
│   ├── batching/                    # Adaptive batching tests (G4)
│   └── stress/                      # Stress tests (G6, @pytest.mark.slow)
├── main.py                          # CLI entry point: gateway | keeper
├── AGENTS.md                        # Code paradigm & development guidelines
├── TESTING.md                       # Testing documentation index
├── TESTING-GUIDE.md                 # How to write tests (Golden Rule, CanonicalConfig)
├── TESTING-RUN.md                   # How to run tests (Makefile targets, groups G1–G6)
├── TESTING-GATEKEEPER.md            # Zero-hardcodes enforcement architecture
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                   # Dependencies + ruff/black/pytest config
├── pyrightconfig.json               # Type checking: basic global, strict on core/ + config/
├── poetry.lock
├── poetry.toml
├── Makefile
└── .env.example
```

## Testing

> See [TESTING.md](TESTING.md) for the full testing documentation index.

Quick reference:

```bash
make test         # G1–G5 (~3 s)
make test-slow    # G6 stress tests
make test-all     # G1–G6
make ci           # lint + typecheck + test
```

Quality gates: pyright → ruff → black → pytest → gatekeeper (see `.github/workflows/quality.yml`).

## Development Guidelines

Code paradigm, conventions, and architecture patterns are documented in [AGENTS.md](AGENTS.md).

## Documentation

| Document | Topic |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Code paradigm, naming conventions, error handling, quality gates |
| [TESTING.md](TESTING.md) | Testing index and quick start |
| [TESTING-GUIDE.md](TESTING-GUIDE.md) | Golden Rule, CanonicalConfig, anti-patterns |
| [TESTING-RUN.md](TESTING-RUN.md) | Makefile targets, process-isolation groups, timeout policy |
| [TESTING-GATEKEEPER.md](TESTING-GATEKEEPER.md) | Zero-hardcodes enforcement architecture |
| [docs/CONFIG_SYSTEM.md](docs/CONFIG_SYSTEM.md) | Configuration subsystem architecture |
| [docs/ERRORS.md](docs/ERRORS.md) | ErrorReason classification |
| [docs/ERROR_PARSING.md](docs/ERROR_PARSING.md) | Error parsing rules |
| [docs/DEBUG_MODE.md](docs/DEBUG_MODE.md) | Gateway debug modes |
