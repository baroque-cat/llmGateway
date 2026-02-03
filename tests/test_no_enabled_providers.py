"""
Test edge case when no providers are enabled.
"""

from src.config.schemas import Config, ProviderConfig
from src.core.accessor import ConfigAccessor


def test_no_enabled_providers():
    """Test behavior when all providers are disabled."""
    config = Config()
    config.providers = {
        "disabled_provider1": ProviderConfig(enabled=False),
        "disabled_provider2": ProviderConfig(enabled=False),
    }

    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()

    assert len(enabled_providers) == 0
