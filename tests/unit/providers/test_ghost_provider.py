"""
Simple tests for ghost provider handling logic without complex DB mocking.
"""

from src.config.schemas import Config, ProviderConfig
from src.core.accessor import ConfigAccessor


def test_enabled_providers_filtering():
    """Test that ConfigAccessor correctly returns only enabled providers."""
    config = Config()
    config.providers = {
        "enabled_provider": ProviderConfig(
            enabled=True,
            provider_type="test",
            keys_path="/tmp/keys",
            api_base_url="http://test.com",
            default_model="test-model",
        ),
        "disabled_provider": ProviderConfig(
            enabled=False,
            provider_type="test",
            keys_path="/tmp/keys2",
            api_base_url="http://test2.com",
            default_model="test-model2",
        ),
        "another_enabled": ProviderConfig(
            enabled=True,
            provider_type="test3",
            keys_path="/tmp/keys3",
            api_base_url="http://test3.com",
            default_model="test-model3",
        ),
    }

    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()

    # Should only contain enabled providers
    assert len(enabled_providers) == 2
    assert "enabled_provider" in enabled_providers
    assert "another_enabled" in enabled_providers
    assert "disabled_provider" not in enabled_providers


def test_get_all_providers_includes_disabled():
    """Test that get_all_providers includes both enabled and disabled."""
    config = Config()
    config.providers = {
        "enabled_provider": ProviderConfig(enabled=True),
        "disabled_provider": ProviderConfig(enabled=False),
    }

    accessor = ConfigAccessor(config)
    all_providers = accessor.get_all_providers()

    assert len(all_providers) == 2
    assert "enabled_provider" in all_providers
    assert "disabled_provider" in all_providers
