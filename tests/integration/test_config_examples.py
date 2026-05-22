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
    "GATEWAY_HOST": "0.0.0.0",
    "GATEWAY_PORT": "55300",
    "GATEWAY_WORKERS": "4",
    "KEEPER_METRICS_PORT": "9090",
    "GEMINI_PROD_TOKEN": "test_token_prod",
    "GEMINI_MINIMAL_TOKEN": "test_token_minimal",
    "DEEPSEEK_TOKEN": "test_token_deepseek",
    "ANTHROPIC_TOKEN": "test_token_anthropic",
    "ANTHROPIC_HOME_TOKEN": "test_token_anthropic_home",
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
    assert config.keeper.max_concurrent_providers == 10

    # Check Providers
    assert "gemini-production" in config.providers
    gemini = config.providers["gemini-production"]
    assert gemini.provider_type == "gemini"
    assert gemini.enabled is True
    assert gemini.api_base_url == "https://generativelanguage.googleapis.com"
    # Verify default_model logic (formerly handled by templates, formerly "models" field)
    assert "gemini-2.5-flash" in gemini.default_model
    assert gemini.default_model["gemini-2.5-flash"].endpoint_suffix == ":generateContent"
    # Verify that the old "models" attribute no longer exists on ProviderConfig
    assert not hasattr(gemini, "models"), "ProviderConfig should not have a 'models' attribute"

    assert "deepseek-main" in config.providers
    deepseek = config.providers["deepseek-main"]
    assert deepseek.provider_type == "openai_like"
    assert "deepseek-chat" in deepseek.default_model

    # Check Anthropic provider
    assert "anthropic-production" in config.providers
    anthropic = config.providers["anthropic-production"]
    assert anthropic.provider_type == "anthropic"
    assert anthropic.enabled is True
    assert anthropic.api_base_url == "https://api.anthropic.com"
    assert "claude-sonnet-4-20250514" in anthropic.default_model
    assert "claude-opus-4-20250514" in anthropic.default_model


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


def test_minimal_config_gateway_defaults(mock_env):
    """IT-Y07: Load config/example_minimal_config.yaml → config.gateway.host == "0.0.0.0", port == 55300, workers == 4 (defaults applied)."""
    loader = ConfigLoader(path="config/example_minimal_config.yaml")
    config = loader.load()
    # The minimal config does not define gateway; defaults from defaults.py should be applied.
    assert config.gateway.host == "0.0.0.0"
    assert config.gateway.port == 55300
    assert config.gateway.workers == 4


# --- Dedicated HTTP Client Tests (G6: Section 7) ---


def test_full_config_dedicated_http_client_in_yaml():
    """IT-Y07-2: Raw example_full_config.yaml contains 'dedicated_http_client' field
    for every provider (with a comment explaining its purpose)."""
    yaml = YAML()
    with open("config/example_full_config.yaml", encoding="utf-8") as f:
        data = yaml.load(f)

    providers_section = data["providers"]
    for provider_name, provider_data in providers_section.items():
        assert "dedicated_http_client" in provider_data, (
            f"Provider '{provider_name}' in example_full_config.yaml "
            f"does not contain 'dedicated_http_client' key. "
            f"Available keys: {list(provider_data.keys())}"
        )
        assert provider_data["dedicated_http_client"] is False, (
            f"Provider '{provider_name}' has dedicated_http_client="
            f"{provider_data['dedicated_http_client']}, expected False"
        )


def test_full_config_dedicated_http_client_loaded(mock_env):
    """IT-Y07-2: ConfigLoader.load() on example_full_config.yaml → every provider
    has dedicated_http_client attribute."""
    loader = ConfigLoader(path="config/example_full_config.yaml")
    config = loader.load()

    for provider_name, provider in config.providers.items():
        assert hasattr(
            provider, "dedicated_http_client"
        ), f"Provider '{provider_name}' loaded object has no 'dedicated_http_client' attribute"
        assert provider.dedicated_http_client is False, (
            f"Provider '{provider_name}' has dedicated_http_client="
            f"{provider.dedicated_http_client}, expected False"
        )


def test_old_models_key_rejected_by_extra_forbid(mock_env):
    """Verifies that the deprecated 'models:' YAML key is rejected by
    ProviderConfig's extra_forbid policy, preventing silent misconfiguration."""
    from pydantic import ValidationError

    from src.config.schemas import ProviderConfig

    # Attempting to create a ProviderConfig with the old "models" field
    # should raise a ValidationError due to extra="forbid".
    with pytest.raises(ValidationError, match="models"):
        ProviderConfig(
            provider_type="gemini",
            api_base_url="https://example.com",
            models={"gemini-2.5-flash": {"endpoint_suffix": ":generateContent"}},
        )


def test_default_model_is_dict_not_str(mock_env):
    """Verifies that ProviderConfig.default_model is dict[str, ModelInfo],
    not a plain string. The old 'default_model: "gemini-2.5-flash"' string
    format must no longer be accepted."""
    from pydantic import ValidationError

    from src.config.schemas import ProviderConfig

    # A string value for default_model should be rejected — it must be a dict.
    with pytest.raises(ValidationError, match="default_model"):
        ProviderConfig(
            provider_type="gemini",
            api_base_url="https://example.com",
            default_model="gemini-2.5-flash",
        )

    # A dict value for default_model should be accepted.
    provider = ProviderConfig(
        provider_type="gemini",
        api_base_url="https://example.com",
        default_model={
            "gemini-2.5-flash": {"endpoint_suffix": ":generateContent"},
        },
    )
    assert isinstance(provider.default_model, dict)
    assert "gemini-2.5-flash" in provider.default_model


def test_full_config_default_model_structure(mock_env):
    """Verifies that all providers in example_full_config.yaml have
    default_model as a dict[str, ModelInfo] with correct structure."""
    loader = ConfigLoader(path="config/example_full_config.yaml")
    config = loader.load()

    for provider_name, provider in config.providers.items():
        assert isinstance(provider.default_model, dict), (
            f"Provider '{provider_name}' default_model should be a dict, "
            f"got {type(provider.default_model).__name__}"
        )
        for model_name, model_info in provider.default_model.items():
            assert hasattr(model_info, "endpoint_suffix"), (
                f"Model '{model_name}' in provider '{provider_name}' "
                f"should be a ModelInfo instance with endpoint_suffix"
            )
            assert hasattr(model_info, "test_payload"), (
                f"Model '{model_name}' in provider '{provider_name}' "
                f"should be a ModelInfo instance with test_payload"
            )
