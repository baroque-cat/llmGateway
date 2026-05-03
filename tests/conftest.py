"""Global test configuration.

Sets default environment variables required by the config loader after the
consolidate-configuration-env-vars change. Uses setdefault to avoid
overriding values set by individual tests.
"""

import os


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
    }
    for key, value in _defaults.items():
        os.environ.setdefault(key, value)


_setup_default_env_vars()
