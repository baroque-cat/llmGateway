# src/providers/__init__.py

from typing import Dict, Type
from src.core.types import IProvider
from src.config.schemas import ProviderConfig

# Import concrete provider implementations
from src.providers.base import AIBaseProvider
from src.providers.base.impl.openai_like import OpenAILikeProvider
from src.providers.base.impl.gemini import GeminiProvider

# A registry to map provider type names from the config to their classes.
# This makes the system easily extensible. To add a new provider, just
# add its class here.
_PROVIDER_CLASSES: Dict[str, Type[AIBaseProvider]] = {
    "openai_like": OpenAILikeProvider,
    "gemini": GeminiProvider,
}

def get_provider(provider_name: str, config: ProviderConfig) -> IProvider:
    """
    Factory function to create a provider instance based on its name.

    Args:
        provider_name: The name of the provider type (e.g., 'openai_like', 'gemini').
        config: The configuration object for this specific provider instance.

    Returns:
        An instance of the requested provider class, conforming to the IProvider interface.

    Raises:
        ValueError: If the requested provider name is not registered.
    """
    provider_class = _PROVIDER_CLASSES.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown provider type: '{provider_name}'. "
                         f"Available types are: {list(_PROVIDER_CLASSES.keys())}")
    
    # We use the provider_name from the config key as the instance name.
    # The provider_type from config is used for class lookup.
    return provider_class(provider_name=provider_name, config=config)

