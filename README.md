# llmGateway

**A high-performance, asynchronous API gateway for managing and load-balancing LLM provider keys with built-in resilience.**

`llmGateway` is designed to unify multiple (potentially unstable) API keys from various LLM providers into a single, reliable, and manageable entry point. It features proactive health monitoring, intelligent request routing, and robust retry mechanisms to ensure maximum uptime and efficiency.

The system consists of two core, independent components:

1.  **Background Worker ("Keeper"):** Proactively probes the health of API keys and proxies, synchronizes them with on-disk files, and keeps the internal database up-to-date.
2.  **API Gateway ("Conductor"):** Reactively handles incoming requests in real-time, selects the most suitable healthy key, and proxies the request to the target LLM API.

## Key Features

*   **🚀 High Performance:** Fully asynchronous architecture built on FastAPI and Python's `asyncio`.
*   **🔄 Smart Retries:** Configurable retry policies for failed requests to handle transient provider errors gracefully.
*   **🛡️ Proactive Monitoring:** Background worker continuously validates key status to maintain an accurate health pool.
*   **📦 Multi-Provider Support:** Adapters for OpenAI-compatible APIs and Google Gemini.
*   **🧠 Smart Caching:** Optimized handling of shared API keys to prevent rate limit exhaustion.
*   **📊 Prometheus Metrics:** Built-in `/metrics` endpoint for professional monitoring and observability.

## Architecture

The project follows a clean, modular design with a clear separation of concerns.

```
/llmGateway
├── config/
│   └── providers.yaml          # Main configuration file
├── examples/                   # Example configuration files
├── keys/                       # Directory for API key files
├── logs/                       # Directory for log files
├── src/
│   ├── config/                 # Configuration loading, validation, and access
│   │   ├── __init__.py         # Configuration facade (Singleton)
│   │   ├── defaults.py         # Default global settings
│   │   ├── loader.py           # Smart configuration assembler
│   │   ├── logging_config.py   # Logging setup
│   │   ├── schemas.py          # Strict data models (source of truth)
│   │   └── validator.py        # Business logic validator
│   ├── core/                   # Core abstractions, models, and contracts
│   │   ├── accessor.py         # Safe configuration accessor facade
│   │   ├── constants.py        # Standardized enums (e.g., ErrorReason)
│   │   ├── http_client_factory.py # Factory for managing HTTP clients
│   │   ├── interfaces.py       # Core interfaces (IProvider, IResourceSyncer)
│   │   ├── models.py           # Core data models (e.g., CheckResult)
│   │   └── probes.py           # Abstract base class for resource probes
│   ├── db/
│   │   └── database.py         # PostgreSQL database layer
│   ├── providers/              # Provider-specific logic
│   │   ├── __init__.py         # Provider factory
│   │   ├── base.py             # Abstract base provider class
│   │   └── impl/               # Concrete implementations
│   │       ├── gemini.py       # Google Gemini adapter
│   │       ├── gemini_base.py  # Base class for Google APIs
│   │       └── openai_like.py  # OpenAI-compatible API adapter
│   └── services/               # Business logic and orchestration
│       ├── __init__.py
│       ├── background_worker.py # Background task orchestrator (Keeper)
│       ├── gateway_cache.py    # Cache for keys and models (fixes shared-key bug)
│       ├── gateway_service.py  # Main API Gateway service (Conductor)
│       ├── maintenance.py      # Database maintenance services
│       ├── metrics_exporter.py # Prometheus metrics exporter
│       ├── probes/             # Active resource probes
│       │   └── key_probe.py    # Background key health checker
│       └── synchronizers/      # Disk-to-DB synchronizers
│           ├── key_sync.py     # API key synchronizer
│           └── proxy_sync.py   # Proxy list synchronizer
└── main.py                     # Application entry point
```

## Getting Started

### Prerequisites

*   Python 3.13+
*   [Poetry](https://python-poetry.org/)
*   PostgreSQL (for the database)

### Installation

```bash
git clone https://github.com/your-username/llmGateway.git
cd llmGateway
poetry install
```

### Configuration

1.  Create your configuration file by copying an example:
    ```bash
    cp examples/minimal_config.yaml config/providers.yaml
    ```
2.  Edit `config/providers.yaml` to add your API keys, providers, and desired policies.

### Running with Docker Compose (Recommended)

The easiest and most robust way to run `llmGateway` is with `docker-compose`. This method provides full isolation, simplifies dependency management, and is compatible with rootless container engines like Podman.

1.  **Prepare your configuration**:
    ```bash
    # Copy the example config and .env file
    cp examples/full_config.yaml config/providers.yaml
    cp examples/.env.example .env

    # Edit the files to match your setup
    edit config/providers.yaml
    edit .env
    ```

2.  **Build and start the services**:
    ```bash
    docker-compose up --build -d
    ```

This will start three services: a PostgreSQL database, the API Gateway, and the Background Worker.

> **Why Docker Compose with Podman?**
> This project's `docker-compose.yml` is designed for maximum compatibility and security. It uses named volumes and the `userns_mode: keep-id` directive, which allows it to run seamlessly in **rootless mode** with [Podman](https://podman.io/). Rootless containers enhance security by running without root privileges on the host system, making them ideal for production environments.

### Running from Source (Development)

If you prefer to run the application directly from source (e.g., for development):

*   **Start the API Gateway:**
    ```bash
    poetry run python main.py gateway --host 0.0.0.0 --port 8000
    ```
*   **Start the Background Worker:**
    ```bash
    poetry run python main.py worker
    ```

## Configuration

The system is configured via the `providers.yaml` file. The configuration schema is defined in `src/config/schemas.py`. Key configurable features include:

*   **Retry Policies:** Define how many times and with what backoff strategy to retry failed requests.
*   **Health Probing:** Configure intervals and methods for checking key validity.

> **Note:** The Circuit Breaker pattern is currently **not implemented**, although its configuration structure exists.

## Development

This project adheres to strict development guidelines.

### Testing

```bash
# Run all tests
poetry run pytest

# Run type checking
poetry run pyright

# Run linter
poetry run ruff check src/ tests/

# Format code
poetry run black src/ tests/
```

### Code Style

*   **Python Version:** 3.13+
*   **Asynchronous:** Full `async`/`await` support.
*   **Typing:** Strict type hints for all functions and variables.
*   **Naming:**
    *   Variables/Functions: `snake_case`
    *   Classes: `PascalCase`
    *   Constants: `UPPER_CASE`
*   **Documentation:** Docstrings are required for all public modules, classes, and functions.
*   **Error Handling:** Use typed exceptions and enums from `src.core.constants.ErrorReason`.

## Project Status

*   ✅ **Implemented:** Gateway, Background Worker, Retry Policy, Key Probing, Smart Caching.
*   🚧 **Planned / Not Implemented:** Circuit Breaker functionality.
