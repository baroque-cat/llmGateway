# src/core/types.py

"""
Core Types - Abstract Interfaces and Protocols.

This module defines abstract base classes and interfaces that establish
the fundamental contracts for different components within the system,
ensuring a modular and extensible architecture.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Dict

import httpx

# REFACTORED: Import ConfigAccessor to use it in the new interface contracts.
from src.core.accessor import ConfigAccessor
from src.core.models import CheckResult, RequestDetails
from src.db.database import DatabaseManager


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
        implementation.

        Args:
            path: The URL path of the original request (e.g., '/v1/chat/completions').
            content: The raw byte content (body) of the original request.

        Returns:
            A RequestDetails object containing standardized information, like
            the requested model name, that the gateway can understand and act upon.
        """
        pass

    @abstractmethod
    async def check(self, client: httpx.AsyncClient, token: str, **kwargs) -> CheckResult:
        """
        Checks if an API token is valid for this provider. (Async)

        This method should perform a lightweight, non-blocking test request to determine
        the token's status (valid, invalid, no quota, etc.).

        Args:
            client: An instance of httpx.AsyncClient for making the request.
            token: The API token/key to validate.
            **kwargs: Optional provider-specific arguments (e.g., model for testing).

        Returns:
            A CheckResult object containing the result of the validation.
        """
        pass

    @abstractmethod
    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
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

    @abstractmethod
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies an incoming client request to the target API provider. (Async)

        This method is framework-agnostic. It takes primitive data types
        and an httpx client, making it universally usable.

        Args:
            client: An instance of httpx.AsyncClient for making the request.
            token: A valid API key/token to be used for the outbound request.
            method: The HTTP method of the original request (e.g., "POST").
            headers: A dictionary of headers from the original request.
            path: The URL path of the original request.
            content: The raw byte content (body) of the original request.

        Returns:
            A tuple containing:
            1. The raw `httpx.Response` object from the upstream provider.
            2. A `CheckResult` object generated from the response.
        """
        pass


class IResourceSyncer(ABC):
    """
    Abstract Base Class (Interface) for all resource synchronizers (Async Version).

    This contract defines a universal interface for any service that synchronizes
    resources from a source to a destination.
    """

    # REFACTORED: Add an __init__ method to the contract for proper Dependency Injection.
    # This enforces that all synchronizers are initialized with their dependencies.
    @abstractmethod
    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the syncer with necessary dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        pass

    # REFACTORED: The sync method no longer takes arguments.
    # It will use the dependencies injected via the constructor.
    # This is a BREAKING CHANGE that improves the design.
    @abstractmethod
    async def sync(self):
        """
        Executes one full synchronization cycle for the specific resource type. (Async)
        """
        pass
