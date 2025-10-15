# src/providers/base.py

from abc import abstractmethod
from typing import List, Optional, Dict, Tuple

import httpx  # --- MODIFIED: Import httpx instead of requests ---

from src.core.types import IProvider
from src.core.models import CheckResult
from src.config.schemas import ProviderConfig


class AIBaseProvider(IProvider):
    """
    Abstract Base Class for all AI service providers (Async and Framework-Agnostic).

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

        This method cleans the incoming headers by removing sensitive or problematic
        ones and merges them with the provider-specific headers required for
        upstream authentication. It now operates on a simple dictionary, making it
        framework-agnostic.

        Args:
            token: The API token for the upstream service.
            incoming_headers: A dictionary of headers from the client's request.

        Returns:
            A dictionary of cleaned and prepared headers for the outbound request.
        """
        # Copy headers, converting keys to lowercase for case-insensitive checks.
        cleaned_headers = {k.lower(): v for k, v in incoming_headers.items()}
        
        # Headers to remove:
        # - host: httpx will set this correctly based on the target URL.
        # - authorization, x-goog-api-key: These are client->gateway auth headers;
        #   we must remove them to replace with our gateway->provider auth.
        # - content-length, content-type: httpx handles these automatically.
        headers_to_remove = [
            'host', 'authorization', 'x-goog-api-key',
            'content-length', 'content-type'
        ]
        for h in headers_to_remove:
            cleaned_headers.pop(h, None)
        
        # Get provider-specific headers (e.g., {'Authorization': 'Bearer ...'})
        provider_headers = self._get_headers(token) or {}
        # Merge our provider auth headers into the cleaned client headers.
        # Provider headers take precedence in case of a key collision.
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
    async def check(self, token: str, **kwargs) -> CheckResult:
        """
        Checks if an API token is valid for this provider. (Async)
        This must be implemented by concrete provider classes.

        Args:
            token: The API token/key to validate.
            **kwargs: Optional provider-specific arguments.

        Returns:
            A CheckResult object with the validation outcome.
        """
        raise NotImplementedError

    @abstractmethod
    async def inspect(self, token: str, **kwargs) -> List[str]:
        """
        Inspects the capabilities associated with a token. (Async)
        This must be implemented by concrete provider classes.

        Args:
            token: The API token/key for authentication.
            **kwargs: Optional provider-specific arguments.

        Returns:
            A list of available model names.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def proxy_request(
        self, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies an incoming client request to the target API provider. (Async)
        This must be implemented by concrete provider classes.
        """
        raise NotImplementedError
