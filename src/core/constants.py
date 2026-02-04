#!/usr/bin/env python3

"""
Core Constants and Enums - Fundamental constants and enumeration types for the Gateway.

This module defines core constants and enumeration types used throughout the application.
These provide type safety and clear value definitions for system states,
error reasons, and other categorical data.
"""

from enum import Enum, unique


# Constants for shared key optimization
ALL_MODELS_MARKER = "__ALL_MODELS__"


@unique
class ErrorReason(Enum):
    """
    Standardized error reasons for API validation and processing.
    Used across the system for consistent error handling and reporting.
    This enum defines *why* a check failed.
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

    def is_fatal(self) -> bool:
        """
        Check if the error is fatal for the specific API key being used.
        These errors indicate that the key itself is invalid, revoked, has no access,
        or has run out of quota/credits.

        Returns:
            bool: True if the error implies the key should be marked invalid/unusable.
        """
        fatal_errors = {
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
            ErrorReason.NO_QUOTA,
            ErrorReason.NO_MODEL,
        }
        return self in fatal_errors

    def is_client_error(self) -> bool:
        """
        Check if the error is definitively caused by a client-side issue,
        such as an invalid key or insufficient permissions. These errors are typically not retryable.

        Returns:
            bool: True if the error is a client-side fault, False otherwise.
        """
        client_errors = {
            ErrorReason.BAD_REQUEST,
        }
        return self in client_errors


@unique
class Status(str, Enum):
    """
    Represents all possible states for a resource's status in the database.

    This enum is the single source of truth for the `status` column in tables
    like `key_model_status`. By inheriting from `str`, its members can be used
    directly in database queries without needing to call `.value`.
    """

    # Non-error statuses
    VALID = "valid"
    UNTESTED = "untested"

    # Statuses corresponding to error reasons
    UNKNOWN = "unknown"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    OVERLOADED = "overloaded"
    BAD_REQUEST = "bad_request"
    INVALID_KEY = "invalid_key"
    NO_ACCESS = "no_access"
    RATE_LIMITED = "rate_limited"
    NO_QUOTA = "no_quota"
    NO_MODEL = "no_model"


# --- New Enums for Configuration Validation ---


@unique
class DebugMode(Enum):
    """
    Defines the allowed debug logging modes for a provider instance.
    """

    DISABLED = "disabled"
    HEADERS_ONLY = "headers_only"
    FULL_BODY = "full_body"


@unique
class StreamingMode(Enum):
    """
    Defines the allowed streaming modes for a provider instance.
    """

    AUTO = "auto"
    DISABLED = "disabled"


@unique
class ProxyMode(Enum):
    """
    Defines the allowed proxy modes for a provider instance.
    """

    NONE = "none"
    STATIC = "static"
    STEALTH = "stealth"


@unique
class CircuitBreakerMode(Enum):
    """
    Defines the allowed circuit breaker modes for a provider instance.
    """

    AUTO_RECOVERY = "auto_recovery"
    MANUAL_RESET = "manual_reset"
