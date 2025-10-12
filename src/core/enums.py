#!/usr.bin/env python3

"""
Core Enums - Fundamental Enumeration Types for the Gateway.

This module defines core enumeration types used throughout the application.
These enums provide type safety and clear value definitions for system states,
error reasons, and other categorical data.
"""

from enum import Enum, unique


@unique
class ErrorReason(Enum):
    """
    Standardized error reasons for API validation and processing.
    Used across the system for consistent error handling and reporting.
    """

    # General Errors
    UNKNOWN = "unknown"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    OVERLOADED = "overloaded"
    
    # Client-Side & Authentication Errors
    BAD_REQUEST = "bad_request"
    INVALID_KEY = "invalid_key"
    NO_ACCESS = "no_access"  # Access denied, permission issues, or region blocks
    RATE_LIMITED = "rate_limited"

    # Provider-Specific Quota & Model Errors
    NO_QUOTA = "no_quota"
    NO_MODEL = "no_model"


    def is_retryable(self) -> bool:
        """
        Check if an error reason suggests that the operation could succeed on a subsequent attempt.
        This is crucial for deciding whether to re-test a key after a failure.
        
        Returns:
            bool: True if the error is transient and worth retrying, False otherwise.
        """
        retryable_errors = {
            ErrorReason.NETWORK_ERROR,
            ErrorReason.TIMEOUT,
            ErrorReason.RATE_LIMITED,
            ErrorReason.SERVER_ERROR,
            ErrorReason.SERVICE_UNAVAILABLE,
            ErrorReason.OVERLOADED,
        }
        return self in retryable_errors

    def is_client_error(self) -> bool:
        """
        Check if the error is definitively caused by a client-side issue,
        such as an invalid key or insufficient permissions. These errors are typically not retryable.

        Returns:
            bool: True if the error is a client-side fault, False otherwise.
        """
        client_errors = {
            ErrorReason.BAD_REQUEST,
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
        }
        return self in client_errors
