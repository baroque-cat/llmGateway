# src/providers/base.py

from abc import abstractmethod
from typing import List, Optional, Dict

from src.core.types import IProvider
from src.core.models import CheckResult
from src.config.schemas import ProviderConfig


class AIBaseProvider(IProvider):
    """
    Abstract Base Class for all AI service providers.
    It enforces the IProvider contract and provides a common structure
    and helper methods for all concrete provider implementations.
    """

    def __init__(self, provider_name: str, config: ProviderConfig):
        """
        Initializes the base provider.

        Args:
            provider_name: The unique name of the provider.
            config: The configuration object specific to this provider.
        """
        if not provider_name:
            raise ValueError("Provider name cannot be empty.")
        
        self.name = provider_name
        self.config = config

    @abstractmethod
    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs the necessary headers for API requests.
        Must be implemented by subclasses.

        Args:
            token: The API token to be used for authentication.

        Returns:
            A dictionary of headers or None if token is invalid.
        """
        raise NotImplementedError

    @abstractmethod
    def check(self, token: str, **kwargs) -> CheckResult:
        """
        Checks if an API token is valid for this provider.
        This must be implemented by concrete provider classes.

        Args:
            token: The API token/key to validate.
            **kwargs: Optional provider-specific arguments.

        Returns:
            A CheckResult object with the validation outcome.
        """
        raise NotImplementedError

    @abstractmethod
    def inspect(self, token: str, **kwargs) -> List[str]:
        """
        Inspects the capabilities associated with a token, such as available models.
        This must be implemented by concrete provider classes.

        Args:
            token: The API token/key for authentication.
            **kwargs: Optional provider-specific arguments.

        Returns:
            A list of available model names.
        """
        raise NotImplementedError
