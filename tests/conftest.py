"""Global test configuration.

Sets default environment variables required by the config loader after the
consolidate-configuration-env-vars change. Uses setdefault to avoid
overriding values set by individual tests.
"""

import os

import pytest


def _setup_default_env_vars() -> None:
    """Set default env vars for all tests. Only sets if not already present."""
    _defaults: dict[str, str] = {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_USER": "test_user",
        "DB_PASSWORD": "test_password",
        "DB_NAME": "test_db",
        "GATEWAY_HOST": "0.0.0.0",
        "GATEWAY_PORT": "55300",
        "GATEWAY_WORKERS": "4",
        "KEEPER_METRICS_PORT": "9090",
        "LLM_PROVIDER_DEFAULT_TOKEN": "test_token",
        "METRICS_ACCESS_TOKEN": "test_metrics_token",
        "METRICS_BACKEND": "",
        "PROMETHEUS_MULTIPROC_DIR": "",
        "GEMINI_PROD_TOKEN": "test_gemini_token",
        "DEEPSEEK_TOKEN": "test_deepseek_token",
        "ANTHROPIC_TOKEN": "test_anthropic_token",
        "QWEN_HOME_TOKEN": "test_qwen_token",
    }
    for key, value in _defaults.items():
        os.environ.setdefault(key, value)


_setup_default_env_vars()


# ── Custom CLI options ──


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI options for the test suite.

    --run-postgres: opt-in flag for tests requiring a live PostgreSQL instance.
    Without this flag, postgres-marked tests are skipped.
    """
    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.postgres",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers during pytest configuration."""
    config.addinivalue_line(
        "markers", "postgres: tests requiring a live PostgreSQL instance"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip postgres-marked tests unless --run-postgres is set."""
    if not config.getoption("--run-postgres"):
        skip_postgres = pytest.mark.skip(reason="--run-postgres not specified")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip_postgres)
