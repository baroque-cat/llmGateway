# src/providers/base.py

import logging
from abc import abstractmethod
from typing import List, Optional, Dict, Tuple

import httpx

from src.core.types import IProvider
# --- Import the required data models ---
from src.core.models import CheckResult, RequestDetails
from src.config.schemas import ProviderConfig
from src.core.enums import ErrorReason

# --- Get a logger for this module ---
logger = logging.getLogger(__name__)


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

    # --- REFACTORED: Protected helper method for sending requests (Template Method pattern) ---
    async def _send_proxy_request(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Sends a pre-built proxy request and parses the result.

        This method encapsulates the common logic for sending a request,
        handling network errors, and processing successful/failed responses.
        It delegates the parsing of provider-specific errors to the
        `_parse_proxy_error` method.

        Args:
            client: The httpx.AsyncClient to use for the request.
            request: The pre-built httpx.Request object.

        Returns:
            A tuple containing the raw httpx.Response and a parsed CheckResult.
        """
        try:
            upstream_response = await client.send(request, stream=True)
            
            if upstream_response.is_success:
                # --- FIXED: Do NOT access .elapsed on a successful streaming response ---
                # The response body has not been read yet, so accessing .elapsed
                # would raise a RuntimeError. For a successful proxy, we only
                # need to confirm it's okay and pass the status code.
                check_result = CheckResult.success(status_code=upstream_response.status_code)
            else:
                # For failed responses, delegate parsing to the provider-specific method.
                # This method is responsible for safely reading the response.
                check_result = await self._parse_proxy_error(upstream_response)

        except httpx.RequestError as e:
            error_message = f"Upstream request failed with a network-level error: {e}"
            logger.error(error_message)
            check_result = CheckResult.fail(ErrorReason.NETWORK_ERROR, error_message, status_code=503)
            # Create a synthetic response for the gateway to handle gracefully.
            upstream_response = httpx.Response(503, content=error_message.encode())
        
        return upstream_response, check_result

    # --- Abstract method for provider-specific error parsing ---
    @abstractmethod
    async def _parse_proxy_error(self, response: httpx.Response) -> CheckResult:
        """
        (Abstract) Parses a failed httpx.Response to generate a CheckResult.

        This method MUST be implemented by subclasses. It is responsible for
        safely reading the response body and mapping the provider-specific
        error content to a standardized ErrorReason. This is where the fix
        for the '.elapsed' RuntimeError is implemented for *failed* requests.

        Args:
            response: The failed httpx.Response object from the upstream service.

        Returns:
            A CheckResult object detailing the failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        (Abstract) Parses the raw incoming request to extract provider-specific details.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        (Abstract) Constructs the necessary authentication headers for API requests.
        Must be implemented by subclasses.
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
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, query_params: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        (Abstract) Proxies an incoming client request to the target API provider. (Async)
        """
        raise NotImplementedError

