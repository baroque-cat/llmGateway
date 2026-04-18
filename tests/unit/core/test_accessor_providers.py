"""
Test edge case when no providers are enabled.
"""

from src.config.schemas import Config, ProviderConfig
from src.core.accessor import ConfigAccessor


def test_no_enabled_providers():
    """Test behavior when all providers are disabled."""
    config = Config()
    config.providers = {
        "disabled_provider1": ProviderConfig(
            enabled=False, provider_type="test1", keys_path="keys/test1/"
        ),
        "disabled_provider2": ProviderConfig(
            enabled=False, provider_type="test2", keys_path="keys/test2/"
        ),
    }

    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()

    assert len(enabled_providers) == 0
