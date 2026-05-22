"""
Test edge case when no providers are enabled.

Includes tests moved from integration/test_ghost_provider_integration.py:
  - test_complete_ghost_provider_workflow
  - test_worker_only_processes_enabled_providers
  - test_empty_enabled_providers_handling
"""

from src.config.schemas import Config, ModelInfo, ProviderConfig
from src.core.accessor import ConfigAccessor


def test_no_enabled_providers():
    """Test behavior when all providers are disabled."""
    config = Config()
    config.providers = {
        "disabled_provider1": ProviderConfig(
            enabled=False, provider_type="openai_like"
        ),
        "disabled_provider2": ProviderConfig(enabled=False, provider_type="gemini"),
    }

    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()

    assert len(enabled_providers) == 0


# --- Tests moved from integration/test_ghost_provider_integration.py ---


def test_complete_ghost_provider_workflow():
    """
    Test the complete workflow of ghost provider handling.

    Scenario:
    - Initially have 3 providers: enabled, disabled, and to-be-deleted
    - After config update, only enabled provider remains
    - Database should reflect this change after sync
    - Worker should only process enabled provider
    """
    # Initial configuration with 3 providers
    initial_config = Config()
    initial_config.providers = {
        "active_provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            api_base_url="http://active.com",
            default_model={"model1": ModelInfo()},
        ),
        "disabled_provider": ProviderConfig(
            enabled=False,
            provider_type="openai_like",
            api_base_url="http://disabled.com",
            default_model={"model2": ModelInfo()},
        ),
        "ghost_provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            api_base_url="http://ghost.com",
            default_model={"model3": ModelInfo()},
        ),
    }

    accessor = ConfigAccessor(initial_config)

    # Verify initial state
    all_providers = accessor.get_all_providers()
    enabled_providers = accessor.get_enabled_providers()

    assert len(all_providers) == 3
    assert len(enabled_providers) == 2  # active + ghost
    assert "active_provider" in enabled_providers
    assert "ghost_provider" in enabled_providers
    assert "disabled_provider" not in enabled_providers

    # Simulate config update: remove ghost_provider entirely
    updated_config = Config()
    updated_config.providers = {
        "active_provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            api_base_url="http://active.com",
            default_model={"model1": ModelInfo()},
        ),
        "disabled_provider": ProviderConfig(
            enabled=False,
            provider_type="openai_like",
            api_base_url="http://disabled.com",
            default_model={"model2": ModelInfo()},
        ),
        # ghost_provider is completely removed
    }

    updated_accessor = ConfigAccessor(updated_config)

    # Verify updated state
    updated_all_providers = updated_accessor.get_all_providers()
    updated_enabled_providers = updated_accessor.get_enabled_providers()

    assert len(updated_all_providers) == 2
    assert len(updated_enabled_providers) == 1
    assert "active_provider" in updated_enabled_providers
    assert "ghost_provider" not in updated_all_providers
    assert "disabled_provider" in updated_all_providers
    assert "disabled_provider" not in updated_enabled_providers


def test_worker_only_processes_enabled_providers():
    """Verify that the worker logic correctly filters to enabled providers only."""
    config = Config()
    config.providers = {
        "provider_a": ProviderConfig(enabled=True, provider_type="openai_like"),
        "provider_b": ProviderConfig(enabled=False, provider_type="openai_like"),
        "provider_c": ProviderConfig(enabled=True, provider_type="openai_like"),
        "provider_d": ProviderConfig(enabled=False, provider_type="openai_like"),
    }

    accessor = ConfigAccessor(config)
    enabled_provider_names = list(accessor.get_enabled_providers().keys())

    # These are the names that should be passed to database queries
    assert len(enabled_provider_names) == 2
    assert "provider_a" in enabled_provider_names
    assert "provider_c" in enabled_provider_names
    assert "provider_b" not in enabled_provider_names
    assert "provider_d" not in enabled_provider_names


def test_empty_enabled_providers_handling():
    """Test that the system handles the case where no providers are enabled."""
    config = Config()
    # No providers at all
    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()
    assert len(enabled_providers) == 0

    # All providers disabled
    config.providers = {
        "p1": ProviderConfig(enabled=False, provider_type="openai_like"),
        "p2": ProviderConfig(enabled=False, provider_type="openai_like"),
    }
    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()
    assert len(enabled_providers) == 0


# --- Tests for get_model_info and get_default_model_info ---


def test_get_model_info_from_default_model():
    """Test get_model_info retrieves the correct ModelInfo and returns None for unknown models."""
    config = Config()
    expected_model_info = ModelInfo(
        endpoint_suffix="/v1/chat", test_payload={"dummy": "payload"}
    )
    config.providers = {
        "my-provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            default_model={"gpt-4": expected_model_info},
        ),
    }

    accessor = ConfigAccessor(config)

    # Verify retrieval of an existing model
    result = accessor.get_model_info("my-provider", "gpt-4")
    assert result is expected_model_info

    # Verify retrieval of a non-existent model returns None
    result_none = accessor.get_model_info("my-provider", "nonexistent")
    assert result_none is None


def test_get_default_model_info_returns_first_value():
    """Test get_default_model_info returns the first value from the default_model dict."""
    config = Config()
    model_a = ModelInfo(endpoint_suffix="/v1/chat", test_payload={})
    model_b = ModelInfo(endpoint_suffix="/v1/completions", test_payload={})
    config.providers = {
        "my-provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            default_model={"gpt-4": model_a, "gpt-3.5": model_b},
        ),
    }

    accessor = ConfigAccessor(config)
    result = accessor.get_default_model_info("my-provider")
    assert result is model_a


def test_get_default_model_info_returns_none_for_empty():
    """Test get_default_model_info returns None when default_model dict is empty."""
    config = Config()
    config.providers = {
        "my-provider": ProviderConfig(
            enabled=True,
            provider_type="openai_like",
            default_model={},
        ),
    }

    accessor = ConfigAccessor(config)
    result = accessor.get_default_model_info("my-provider")
    assert result is None
