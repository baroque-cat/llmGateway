# llmGateway

API gateway for managing LLM provider keys — health monitoring, request routing, and retry.

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
src/
  config/                     # Configuration schema, loader, defaults
    schemas.py                # Pydantic models — source of truth
    loader.py                 # YAML loader with env var resolution
    defaults.py               # Global default values
    error_formatter.py        # Validation error formatting
    logging_config.py         # Logging setup
  core/                       # Abstractions, contracts, pure functions
    constants.py              # ErrorReason, Status enums
    models.py                 # CheckResult, DatabaseTableHealth, etc.
    interfaces.py             # ABCs: IProvider, IResourceProbe, IKeyPurger, ...
    probes.py                 # IResourceProbe base class + dispatch
    accessor.py               # ConfigAccessor — typed config facade
    policy_utils.py           # compute_next_check_time(), should_vacuum()
    retry.py                  # AsyncRetrier for transient DB errors
    atomic_io.py              # Atomic NDJSON file writes
    http_client_factory.py    # httpx.AsyncClient factory per provider
    batching/
      adaptive.py             # AdaptiveBatchController (3-priority algorithm)
  db/
    database.py               # PostgreSQL layer: pool, repositories, queries
  providers/                  # LLM provider implementations
    base.py                   # AIBaseProvider — shared proxy logic
    impl/
      openai_like.py          # OpenAI-compatible API
      anthropic.py            # Anthropic API
      gemini.py               # Gemini (thin wrapper)
      gemini_base.py          # Gemini base implementation
  services/                   # Application services
    keeper.py                 # Keeper entry point + APScheduler setup
    gateway/                  # Conductor (API Gateway)
      gateway_service.py      # FastAPI app: routing, retry, streaming
      gateway_cache.py        # In-memory key pool + auth cache
      sanitize_content.py     # Debug-mode content redaction
    key_probe.py              # API key health probing
    key_purger.py             # Stopped key cleanup + provider deletion
    db_maintainer.py          # Conditional VACUUM ANALYZE + Prometheus
    inventory_exporter.py     # NDJSON key snapshots and status export
    metrics_exporter.py       # Prometheus metrics
    synchronizers/
      key_sync.py             # Key file → DB synchronization
      proxy_sync.py           # Proxy file → DB synchronization
```

## Development

```bash
poetry install --with dev

# Type checking
poetry run pyright src/ main.py

# Linting
poetry run ruff check src/ main.py

# Formatting
poetry run black src/ main.py

# Tests
poetry run pytest tests/ -v
```
