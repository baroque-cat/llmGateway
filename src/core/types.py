#!/usr/bin/env python3

"""
Core Types - Abstract Interfaces and Protocols.

This module defines abstract base classes and interfaces that establish
the fundamental contracts for different components within the system,
ensuring a modular and extensible architecture.
"""

from abc import ABC, abstractmethod
from typing import List

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

