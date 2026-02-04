# src/providers/__init__.py

import logging

from src.config.schemas import ProviderConfig
from src.core.interfaces import IProvider

# Import concrete provider implementations
from src.providers.base import AIBaseProvider
from src.providers.impl.gemini import GeminiProvider
from src.providers.impl.openai_like import OpenAILikeProvider

logger = logging.getLogger(__name__)

# A registry to map provider type names from the config to their classes.
# This makes the system easily extensible. To add a new provider, just

# add its class here.
_PROVIDER_CLASSES: dict[str, type[AIBaseProvider]] = {
    "openai_like": OpenAILikeProvider,
    "gemini": GeminiProvider,
}


def get_provider(provider_name: str, config: ProviderConfig) -> IProvider:
    """
    Factory function to create a provider instance based on its type from config.

    Args:
        provider_name: The unique instance name of the provider (e.g., 'gemini_personal').
        config: The configuration object for this specific provider instance.

    Returns:
        An instance of the requested provider class, conforming to the IProvider interface.

    Raises:
        ValueError: If the requested provider type is not specified or not registered.
    """
    provider_type = config.provider_type
    if not provider_type:
        raise ValueError(
            f"Provider type is not specified for instance '{provider_name}'."
        )

    provider_class = _PROVIDER_CLASSES.get(provider_type)
    if not provider_class:
        raise ValueError(
            f"Unknown provider type: '{provider_type}' for instance '{provider_name}'. "
            f"Available types are: {list(_PROVIDER_CLASSES.keys())}"
        )

    # We use the provider_name from the config key as the instance name.
    # The provider_type from config is used for class lookup.
    instance = provider_class(provider_name=provider_name, config=config)
    logger.debug(
        f"Successfully created provider instance '{provider_name}' of type '{provider_type}'."
    )

    return instance
