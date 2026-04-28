import os
from unittest.mock import patch

import pytest
from ruamel.yaml import YAML

from src.config.loader import ConfigLoader

# Mock environment variables required by the examples and providers.yaml
MOCK_ENV = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_NAME": "test_db",
    "GEMINI_PROD_TOKEN": "test_token_prod",
    "GEMINI_MINIMAL_TOKEN": "test_token_minimal",
    "DEEPSEEK_TOKEN": "test_token_deepseek",
    "ANTHROPIC_TOKEN": "test_token_anthropic",
    "METRICS_ACCESS_TOKEN": "test_metrics_token",
    # Additional env vars required by config/providers.yaml
    "GEMINI_PRO_HOME_TOKEN": "test_token_pro_home",
    "GEMINI_FLASH_HOME_TOKEN": "test_token_flash_home",
    "DEEPSEEK_HOME_TOKEN": "test_token_deepseek_home",
    "QWEN_HOME_TOKEN": "test_token_qwen_home",
    "KIMI_HOME_TOKEN": "test_token_kimi_home",
    "GLM_HOME_TOKEN": "test_token_glm_home",
}


@pytest.fixture
def mock_env():
    with patch.dict(os.environ, MOCK_ENV):
        yield


def test_load_full_config_example(mock_env):
    """Verifies that config/example_full_config.yaml is valid and loadable."""
    loader = ConfigLoader(path="config/example_full_config.yaml")
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

    # Check Anthropic provider
    assert "anthropic-production" in config.providers
    anthropic = config.providers["anthropic-production"]
    assert anthropic.provider_type == "anthropic"
    assert anthropic.enabled is True
    assert anthropic.api_base_url == "https://api.anthropic.com"
    assert "claude-sonnet-4-20250514" in anthropic.models
    assert "claude-opus-4-20250514" in anthropic.models


def test_load_minimal_config_example(mock_env):
    """Verifies that config/example_minimal_config.yaml is valid and loadable."""
    loader = ConfigLoader(path="config/example_minimal_config.yaml")
    config = loader.load()

    assert config.database.password == "test_password"

    assert "gemini-minimal" in config.providers
    gemini = config.providers["gemini-minimal"]
    assert gemini.provider_type == "gemini"
    # Check that defaults (merged from defaults.py) are present even if not in minimal config
    # e.g. timeouts should come from defaults
    assert gemini.timeouts.connect == 15.0
    assert gemini.timeouts.read == 300.0

    # Check that worker_health_policy defaults are correctly applied
    assert gemini.worker_health_policy.on_success_hr == 24
    assert gemini.worker_health_policy.adaptive_batching.start_batch_size == 10
    assert gemini.worker_health_policy.on_overload_min == 30


# --- YAML Config & Defaults Order Tests ---


def test_providers_yaml_gateway_values(mock_env):
    """IT-Y01: Load config/providers.yaml → config.gateway exists, values match YAML."""
    loader = ConfigLoader(path="config/providers.yaml")
    config = loader.load()
    assert config.gateway.host == "0.0.0.0"
    assert config.gateway.port == 55300
    assert config.gateway.workers == 4


def test_providers_yaml_database_pool(mock_env):
    """IT-Y02: Load config/providers.yaml → config.database.pool exists, min_size/max_size match YAML."""
    loader = ConfigLoader(path="config/providers.yaml")
    config = loader.load()
    assert config.database.pool.min_size == 1
    assert config.database.pool.max_size == 15


def test_providers_yaml_key_order():
    """IT-Y03: Read providers.yaml as dict → keys in order: logging, metrics, gateway, worker, database, providers."""
    yaml = YAML()
    with open("config/providers.yaml", encoding="utf-8") as f:
        data = yaml.load(f)
    expected_order = [
        "logging",
        "metrics",
        "gateway",
        "worker",
        "database",
        "providers",
    ]
    assert list(data.keys()) == expected_order


def test_full_config_gateway_and_database_pool(mock_env):
    """IT-Y04: Load config/example_full_config.yaml → config.gateway and config.database.pool exist."""
    loader = ConfigLoader(path="config/example_full_config.yaml")
    config = loader.load()
    assert hasattr(config, "gateway")
    assert hasattr(config.database, "pool")
    assert config.gateway.host == "0.0.0.0"
    assert config.gateway.port == 55300
    assert config.database.pool.min_size == 1
    assert config.database.pool.max_size == 15


def test_full_config_key_order():
    """IT-Y05: Read example_full_config.yaml as dict → keys in order: logging, metrics, gateway, worker, database, providers."""
    yaml = YAML()
    with open("config/example_full_config.yaml", encoding="utf-8") as f:
        data = yaml.load(f)
    expected_order = [
        "logging",
        "metrics",
        "gateway",
        "worker",
        "database",
        "providers",
    ]
    assert list(data.keys()) == expected_order


def test_minimal_config_gateway_defaults(mock_env):
    """IT-Y07: Load config/example_minimal_config.yaml → config.gateway.host == "0.0.0.0", port == 55300, workers == 4 (defaults applied)."""
    loader = ConfigLoader(path="config/example_minimal_config.yaml")
    config = loader.load()
    # The minimal config does not define gateway; defaults from defaults.py should be applied.
    assert config.gateway.host == "0.0.0.0"
    assert config.gateway.port == 55300
    assert config.gateway.workers == 4
