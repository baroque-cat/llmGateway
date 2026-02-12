# src/core/types.py

"""
Core Types - Abstract Interfaces and Protocols.

This module defines abstract base classes and interfaces that establish
the fundamental contracts for different components within the system,
ensuring a modular and extensible architecture.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, TypedDict

import httpx

# Import the necessary data models and dependencies for type hints.
from src.core.accessor import ConfigAccessor
from src.core.models import CheckResult, RequestDetails
from src.db.database import DatabaseManager

# --- TypedDicts for Background Worker's Synchronization State ---
# These structures provide type safety for the data collected during the
# "Read Phase" of the background worker's synchronization cycle.


class ProviderKeyState(TypedDict):
    """Represents the desired state for keys of a single provider."""

    keys_from_files: set[str]
    models_from_config: list[str]


class ProviderProxyState(TypedDict):
    """Represents the desired state for proxies of a single provider."""

    proxies_from_files: set[str]


# --- Core Interfaces ---


class IProvider(ABC):
    """
    The core provider interface (contract) - Async, Framework-Agnostic, and DI-ready.

    This abstract base class defines the essential async methods that every
    AI service provider must implement. It is designed to be completely
    independent of any web framework and relies on Dependency Injection for
    receiving shared resources like the HTTP client.
    """

    @abstractmethod
    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        Parses the raw incoming request to extract provider-specific details.

        This is a key method for the gateway's operation. It delegates the
        complex task of understanding different API request formats (e.g.,
        model in URL path vs. model in JSON body) to the specific provider
        implementation. This is the cornerstone of the polymorphic gateway design.

        Args:
            path: The URL path of the original request (e.g., '/v1/chat/completions').
            content: The raw byte content (body) of the original request.

        Returns:
            A RequestDetails object containing standardized information, like
            the requested model name, that the gateway can understand and act upon.

        Raises:
            ValueError: If parsing fails due to invalid format or missing data.
        """
        pass

    @abstractmethod
    async def check(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> CheckResult:
        """
        Checks if an API token is valid for this provider. (Async)

        This method should perform a lightweight, non-blocking test request to determine
        the token's status (valid, invalid, no quota, etc.). It is primarily
        used by the background worker's KeyProbe.

        Args:
            client: An instance of httpx.AsyncClient for making the request.
            token: The API token/key to validate.
            **kwargs: Optional provider-specific arguments (e.g., model for testing).

        Returns:
            A CheckResult object containing the result of the validation.
        """
        pass

    @abstractmethod
    async def inspect(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> list[str]:
        """
        Inspects the capabilities associated with a token. (Async)

        This method queries the provider's API to list the models or other
        resources accessible with the given token.

        Args:
            client: An instance of httpx.AsyncClient for making the request.
            token: The API token/key for authentication.
            **kwargs: Optional provider-specific arguments.

        Returns:
            A list of available model names.
        """
        pass

    # --- MODIFIED: Added query_params to the method signature ---
    @abstractmethod
    async def proxy_request(
        self,
        client: httpx.AsyncClient,
        token: str,
        method: str,
        headers: dict[str, str],
        path: str,
        query_params: str,
        content: bytes | AsyncGenerator[bytes],
    ) -> tuple[httpx.Response, CheckResult]:
        """
        Proxies an incoming client request to the target API provider. (Async)

        This method is framework-agnostic. It takes primitive data types
        and an httpx client, making it universally usable. It is the primary
        workhorse method called by the API gateway.

        Args:
            client: An instance of httpx.AsyncClient for making the request.
            token: A valid API key/token to be used for the outbound request.
            method: The HTTP method of the original request (e.g., "POST").
            headers: A dictionary of headers from the original request.
            path: The URL path of the original request.
            query_params: The raw query string from the original request (e.g., "alt=sse").
            content: The raw byte content or async generator of bytes (body) of the original request.

        Returns:
            A tuple containing:
            1. The raw `httpx.Response` object from the upstream provider,
               which supports streaming the response body.
            2. A `CheckResult` object generated from the response, used for
               logging and decision-making (e.g., for the circuit breaker).
        """
        pass


class IResourceSyncer(ABC):
    """
    Abstract Base Class (Interface) for all resource synchronizers (Async Version).

    This contract defines a universal interface for any service that synchronizes
    resources from a source (files, config) to a destination (database). It uses
    the "apply state" pattern.
    """

    @abstractmethod
    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the syncer with necessary dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        pass

    @abstractmethod
    def get_resource_type(self) -> str:
        """
        Returns a string identifier for the type of resource this syncer handles.
        This is used by the background worker to route the correct part of the
        desired_state dictionary to this syncer.
        Examples: "keys", "proxies".
        """
        pass

    @abstractmethod
    async def apply_state(
        self, provider_id_map: dict[str, int], desired_state: dict[str, Any]
    ) -> None:
        """
        Executes one full synchronization cycle for the specific resource type
        based on a pre-built desired state. (Async)

        Args:
            provider_id_map: A mapping from provider name to its database ID.
            desired_state: A dictionary where keys are provider names and values
                           are TypedDicts (e.g., ProviderKeyState) representing
                           the complete desired state for that provider's resources.
        """
        pass
