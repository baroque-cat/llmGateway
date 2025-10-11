#!/usr/bin/env python3

"""
Core Types - Abstract Interfaces and Protocols.

This module defines abstract base classes and interfaces that establish
the fundamental contracts for different components within the system,
ensuring a modular and extensible architecture.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple

from flask import Request
import requests

from src.core.models import CheckResult


class IProvider(ABC):
    """
    The core provider interface (contract).

    This abstract base class defines the essential methods that every
    AI service provider must implement. It ensures that the core system
    can interact with any provider in a uniform way, without needing to
    know the specifics of its API.
    """

    @abstractmethod
    def check(self, token: str, **kwargs) -> CheckResult:
        """
        Checks if an API token is valid for this provider.

        This method should perform a lightweight test request to determine
        the token's status (valid, invalid, no quota, etc.).

        Args:
            token: The API token/key to validate.
            **kwargs: Optional provider-specific arguments (e.g., model for testing).

        Returns:
            CheckResult: A structured object containing the result of the validation.
        """
        pass

    @abstractmethod
    def inspect(self, token: str, **kwargs) -> List[str]:
        """
        Inspects the capabilities associated with a token, such as available models.

        This method queries the provider's API to list the models or other
        resources accessible with the given token.

        Args:
            token: The API token/key for authentication.
            **kwargs: Optional provider-specific arguments.

        Returns:
            List[str]: A list of available model names.
        """
        pass

    @abstractmethod
    def proxy_request(self, token: str, request: Request) -> Tuple[requests.Response, CheckResult]:
        """
        Proxies an incoming client request to the target API provider.

        This method is the core of the real-time proxying functionality. It is responsible
        for transforming the incoming Flask request into an outbound request to the
        actual LLM provider, handling provider-specific authentication and URL structuring.

        Args:
            token: A valid API key/token to be used for the outbound request.
            request: The original incoming Flask request object from the client.

        Returns:
            A tuple containing:
            1. The raw `requests.Response` object from the upstream provider.
               This object should be created with `stream=True` to support streaming.
            2. A `CheckResult` object generated from the response, which will be used
               by the proxy service to update the key's status in the database.
        """
        pass

