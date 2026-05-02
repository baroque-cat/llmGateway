# llmGateway

API gateway for managing LLM provider keys — health monitoring, request routing, and retry.

**Supported providers:**
- **Anthropic** — Claude API
- **OpenAI-compatible** — OpenAI, DeepSeek, Groq, and any OpenAI-compatible API
- **Gemini** — Google Gemini API

The system consists of two independent components:

1. **Keeper** — background service for health checks, key synchronization, database maintenance, and key export.
2. **Conductor** (API Gateway) — real-time request routing with key selection, retry policies, and debug modes.

## Quick Start

### Docker (recommended)

```bash
cp config/example_full_config.yaml config/providers.yaml
cp .env.example .env
# edit config/providers.yaml and .env
docker-compose up --build -d
```

Starts three services: PostgreSQL, Conductor (gateway), Keeper.

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
llmGateway
├── config
│   ├── example_full_config.yaml  # all available options
│   └── example_minimal_config.yaml  # quick-start template
├── docs
│   ├── DEBUG_MODE.md             # debug modes: disabled, no_content, full_body
│   └── ERRORS.md                 # error reason catalog
├── src
│   ├── config                    # configuration: schema, loader, defaults, logging
│   │   ├── __init__.py           # public API: load_config(), get_config()
│   │   ├── defaults.py           # global default values
│   │   ├── error_formatter.py    # pretty-prints Pydantic validation errors
│   │   ├── loader.py             # YAML loader with env-var resolution + deep merge
│   │   ├── logging_config.py     # setup_logging(), ComponentNameFilter
│   │   └── schemas.py            # Pydantic v2 models — config source of truth
│   ├── core                      # abstractions, contracts, pure functions
│   │   ├── batching/             # adaptive batch controller (3-priority algorithm)
│   │   ├── accessor.py           # ConfigAccessor — typed read-only config facade
│   │   ├── atomic_io.py          # atomic NDJSON file writes
│   │   ├── constants.py          # enums: ErrorReason, KeyStatus, DebugMode, ProviderType
│   │   ├── exception_handler.py  # @handle_exceptions decorator (sync + async)
│   │   ├── http_client_factory.py  # long-lived httpx.AsyncClient per provider
│   │   ├── interfaces.py         # ABCs: IProvider, IResourceSyncer, IProbeDispatcher
│   │   ├── models.py             # CheckResult, DatabaseTableHealth, StatusSummary
│   │   ├── policy_utils.py       # compute_next_check_time(), should_vacuum()
│   │   ├── probes.py             # probe dispatch and batch scheduling
│   │   └── retry.py              # AsyncRetrier for transient DB errors
│   ├── db
│   │   └── database.py           # PostgreSQL: connection pool, repos, migrations
│   ├── providers                 # LLM provider adapters
│   │   ├── __init__.py           # provider factory + registry
│   │   ├── base.py               # AIBaseProvider — shared proxy logic
│   │   └── impl/
│   │       ├── openai_like.py    # OpenAI-compatible API (OpenAI, DeepSeek, Groq...)
│   │       ├── anthropic.py      # Anthropic (Claude) API
│   │       ├── gemini.py         # Google Gemini (thin entry)
│   │       └── gemini_base.py    # Gemini shared implementation
│   └── services                  # application services
│       ├── gateway/              # Conductor — FastAPI API Gateway
│       │   ├── gateway_service.py  # routing, retry, streaming, debug modes
│       │   ├── gateway_cache.py    # in-memory key pool + auth token cache
│       │   ├── response_forwarder.py  # upstream response forwarding
│       │   └── sanitize_content.py    # debug-mode content redaction
│       ├── synchronizers/
│       │   └── key_sync.py       # NDJSON key files → PostgreSQL sync
│       ├── db_maintainer.py      # conditional VACUUM ANALYZE + dead-tuple Prometheus
│       ├── inventory_exporter.py # periodic key snapshot + status inventory (NDJSON)
│       ├── keeper.py             # Keeper entry point: APScheduler + health cycles
│       ├── key_probe.py          # per-key API health probing (WORKER_CHECK)
│       ├── key_purger.py         # stopped key cleanup + provider deletion
│       └── metrics_exporter.py   # Prometheus metrics (key status, adaptive batch)
├── tests
│   ├── diagnostics/              # forward-ref diagnostic helper
│   ├── e2e/                      # end-to-end gateway logging tests
│   ├── integration/              # cross-component integration tests
│   ├── security/                 # security tests (logging, error forwarding)
│   ├── test_batching/            # adaptive batching unit + integration tests
│   └── unit/                     # unit tests mirroring src/ structure
├── main.py                       # CLI entry point: gateway | keeper
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                # deps + ruff/black/isort/pytest config
├── poetry.toml                   # poetry settings (package-mode = false)
└── pyrightconfig.json            # strict type-checking configuration
```
