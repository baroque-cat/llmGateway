# src/providers/impl/moonshot.py

from src.providers.impl.openai_like import OpenAILikeProvider

class MoonShotProvider(OpenAILikeProvider):
    """
    Provider for MoonShot API.

    This class inherits all its functionality from the generic OpenAILikeProvider.
    It exists to allow specific registration and configuration in the system
    under the 'moonshot' provider_type.

    If DeepSeek were to introduce custom error codes or a different authentication
    scheme in the future, the logic could be overridden here without affecting
    other OpenAI-like providers. For now, no overrides are necessary.
    """
    pass
