#!/usr/bin/env python3

"""
Core Models - Fundamental Data Models for the Gateway.

This module defines the core data models used throughout the application.
These models represent the fundamental entities and data structures.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from src.core.enums import ErrorReason


@dataclass
class CheckResult:
    """
    Represents the outcome of an API key validation check.

    This structured object replaces simple boolean or status code returns,
    providing detailed context about the check, including success status,
    error information, and performance metrics.
    """

    available: bool
    error_reason: ErrorReason = ErrorReason.UNKNOWN
    message: str = ""
    response_time: float = 0.0
    status_code: Optional[int] = None

    @property
    def ok(self) -> bool:
        """A convenient alias for 'available'."""
        return self.available

    @classmethod
    def success(cls, message: str = "Key is valid and operational.", response_time: float = 0.0, status_code: int = 200) -> "CheckResult":
        """
        Factory method to create a successful check result.
        """
        return cls(
            available=True,
            error_reason=ErrorReason.UNKNOWN, # No error on success
            message=message,
            response_time=response_time,
            status_code=status_code,
        )

    @classmethod
    def fail(
        cls, reason: ErrorReason, message: str = "", response_time: float = 0.0, status_code: Optional[int] = None
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


class RequestMetadata:
    """
    Represents metadata extracted from a successful provider response.
    This object is designed to be flexible and provider-agnostic.
    """
    parser_callback: Optional[Callable[[str], Dict[str, Any]]] = None

    model_name: str = ""

    def parse(self, response_body: str) -> Dict[str, Any]:
        """
        Executes the parsing callback if it exists.
        """
        if self.parser_callback:
            try:
                return self.parser_callback(response_body)
            except Exception:
                return {}
        return {}
