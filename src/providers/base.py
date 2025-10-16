# src/providers/base.py

from abc import abstractmethod
from typing import List, Optional, Dict, Tuple

import httpx

from src.core.types import IProvider
from src.core.models import CheckResult
from src.config.schemas import ProviderConfig


class AIBaseProvider(IProvider):
    """
    Abstract Base Class for AI providers (Async, Framework-Agnostic, DI-ready).

    It enforces the IProvider contract and provides a common structure
    and helper methods for all concrete provider implementations.
    """

    def __init__(self, provider_name: str, config: ProviderConfig):
        """
        Initializes the base provider.

        Args:
            provider_name: The unique name of the provider instance.
            config: The configuration object specific to this provider.
        """
        if not provider_name:
            raise ValueError("Provider name cannot be empty.")
        
        self.name = provider_name
        self.config = config

    def _prepare_proxy_headers(self, token: str, incoming_headers: Dict) -> Dict:
        """
        Prepares headers for the outbound proxy request from a dictionary.

        This method cleans the incoming headers and merges them with the
        provider-specific headers required for upstream authentication.
        It operates on a simple dictionary, making it framework-agnostic.

        Args:
            token: The API token for the upstream service.
            incoming_headers: A dictionary of headers from the client's request.

        Returns:
            A dictionary of cleaned and prepared headers for the outbound request.
        """
        cleaned_headers = {k.lower(): v for k, v in incoming_headers.items()}
        
        headers_to_remove = [
            'host', 'authorization', 'x-goog-api-key',
            'content-length', 'content-type'
        ]
        for h in headers_to_remove:
            cleaned_headers.pop(h, None)
        
        provider_headers = self._get_headers(token) or {}
        cleaned_headers.update({k.lower(): v for k, v in provider_headers.items()})
        
        return cleaned_headers

    @abstractmethod
    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs the necessary authentication headers for API requests.
        Must be implemented by subclasses.

        Args:
            token: The API token to be used for authentication.

        Returns:
            A dictionary of headers or None if token is invalid.
        """
        raise NotImplementedError

    @abstractmethod
    async def check(self, client: httpx.AsyncClient, token: str, **kwargs) -> CheckResult:
        """
        (Abstract) Checks if an API token is valid for this provider. (Async)
        """
        raise NotImplementedError

    @abstractmethod
    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
        """
        (Abstract) Inspects the capabilities associated with a token. (Async)
        """
        raise NotImplementedError
    
    @abstractmethod
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        (Abstract) Proxies an incoming client request to the target API provider. (Async)
        """
        raise NotImplementedError
