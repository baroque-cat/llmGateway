#!/usr/bin/env python3

"""
Core Models - Fundamental Data Models for the Gateway.

This module defines the core data models used throughout the application.
These models represent the fundamental entities and data structures, ensuring
type safety and clear contracts between different parts of the system.
"""

from dataclasses import dataclass
from typing import Any

from src.core.enums import ErrorReason


@dataclass(frozen=True)
class RequestDetails:
    """
    A data transfer object (DTO) that holds essential details parsed from an incoming request.

    This standardized, immutable structure is returned by a provider's `parse_request_details`
    method. It serves as a decoupling mechanism, allowing the gateway to perform
    actions like model authorization without needing to understand the provider-specific
    request format (e.g., model in URL path vs. model in JSON body).
    """

    model_name: str


@dataclass
class CheckResult:
    """
    Represents the outcome of an API health check or a proxied request attempt.

    This structured object is used by both the background worker ("Хранитель") for
    health probing and the API gateway ("Проводник") for evaluating the result of
    a live request. It provides detailed context, including success status,
    error information, and performance metrics, replacing simple boolean returns.
    """

    available: bool
    error_reason: ErrorReason = ErrorReason.UNKNOWN
    message: str = ""
    response_time: float = 0.0
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        """A convenient alias for 'available'."""
        return self.available

    @classmethod
    def success(
        cls,
        message: str = "Key is valid and operational.",
        response_time: float = 0.0,
        status_code: int = 200,
    ) -> "CheckResult":
        """
        Factory method to create a successful check result.
        """
        return cls(
            available=True,
            error_reason=ErrorReason.UNKNOWN,  # No error reason on success
            message=message,
            response_time=response_time,
            status_code=status_code,
        )

    @classmethod
    def fail(
        cls,
        reason: ErrorReason,
        message: str = "",
        response_time: float = 0.0,
        status_code: int | None = None,
    ) -> "CheckResult":
        """
        Factory method to create a failed check result.
        """
        # If no specific message is provided, use the enum's value for clarity.
        final_message = message or reason.value.replace("_", " ").capitalize()
        return cls(
            available=False,
            error_reason=reason,
            message=final_message,
            response_time=response_time,
            status_code=status_code,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Serializes the CheckResult object to a dictionary.
        """
        return {
            "available": self.available,
            "error_reason": self.error_reason.value,
            "message": self.message,
            "response_time": self.response_time,
            "status_code": self.status_code,
        }
