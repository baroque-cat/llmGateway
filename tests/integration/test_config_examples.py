import os
from unittest.mock import patch

import pytest

from src.config.loader import ConfigLoader

# Mock environment variables required by the examples
MOCK_ENV = {
    "DB_PASSWORD": "test_password",
    "GEMINI_PROD_TOKEN": "test_token_prod",
    "GEMINI_MINIMAL_TOKEN": "test_token_minimal",
    "DEEPSEEK_TOKEN": "test_token_deepseek",
    "METRICS_ACCESS_TOKEN": "test_metrics_token",
}


@pytest.fixture
def mock_env():
    with patch.dict(os.environ, MOCK_ENV):
        yield


def test_load_full_config_example(mock_env):
    """Verifies that examples/full_config.yaml is valid and loadable."""
    loader = ConfigLoader(path="examples/full_config.yaml")
    config = loader.load()

    assert config.database.password == "test_password"
    assert config.worker.max_concurrent_providers == 10

    # Check Providers
    assert "gemini-production" in config.providers
    gemini = config.providers["gemini-production"]
    assert gemini.provider_type == "gemini"
    assert gemini.enabled is True
    assert gemini.api_base_url == "https://generativelanguage.googleapis.com"
    # Verify models logic (formerly handled by templates)
    assert "gemini-2.5-flash" in gemini.models
    assert gemini.models["gemini-2.5-flash"].endpoint_suffix == ":generateContent"

    assert "deepseek-main" in config.providers
    deepseek = config.providers["deepseek-main"]
    assert deepseek.provider_type == "openai_like"
    assert "deepseek-chat" in deepseek.models


def test_load_minimal_config_example(mock_env):
    """Verifies that examples/minimal_config.yaml is valid and loadable."""
    loader = ConfigLoader(path="examples/minimal_config.yaml")
    config = loader.load()

    assert config.database.password == "test_password"

    assert "gemini-minimal" in config.providers
    gemini = config.providers["gemini-minimal"]
    assert gemini.provider_type == "gemini"
    # Check that defaults (merged from defaults.py) are present even if not in minimal config
    # e.g. timeouts should come from defaults
    assert gemini.timeouts.connect == 5.0
    assert gemini.timeouts.read == 20.0

    # Check that worker_health_policy defaults are correctly applied
    assert gemini.worker_health_policy.on_success_hr == 24
    assert gemini.worker_health_policy.batch_size == 10
    assert gemini.worker_health_policy.on_overload_min == 30
