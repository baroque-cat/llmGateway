#!/usr/bin/env python3

"""
Core Models - Fundamental Data Models for the Gateway.

This module defines the core data models used throughout the application.
These models represent the fundamental entities and data structures, ensuring
type safety and clear contracts between different parts of the system.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core.constants import ErrorReason


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

    This structured object is used by both the background worker ("Keeper") for
    health probing and the API gateway ("Conductor") for evaluating the result of
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


@dataclass(frozen=True)
class AdaptiveBatchingParams:
    """Pure data container for ``AdaptiveBatchController`` — no Pydantic dependency.

    Contains all 13 fields needed by the adaptive batching algorithm.
    Conversion from the Pydantic-based ``AdaptiveBatchingConfig`` happens at the
    boundary via ``AdaptiveBatchingConfig.to_params()``.

    Fields:
        start_batch_size: Initial batch size when the controller is first created.
        start_batch_delay_sec: Initial delay in seconds between batches.
        min_batch_size: Minimum allowable batch size (hard floor).
        max_batch_size: Maximum allowable batch size (hard ceiling).
        min_batch_delay_sec: Minimum allowable delay in seconds.
        max_batch_delay_sec: Maximum allowable delay in seconds.
        batch_size_step: Additive step for batch size adjustments.
        delay_step_sec: Additive step for delay adjustments (seconds).
        rate_limit_divisor: Divisor applied to batch size on rate-limit backoff.
        rate_limit_delay_multiplier: Multiplier applied to delay on rate-limit.
        recovery_threshold: Consecutive successes needed for accelerated recovery.
        recovery_step_multiplier: Step multiplier during accelerated recovery.
        failure_rate_threshold: Transient-error rate triggering moderate backoff.
    """

    start_batch_size: int
    start_batch_delay_sec: float
    min_batch_size: int
    max_batch_size: int
    min_batch_delay_sec: float
    max_batch_delay_sec: float
    batch_size_step: int
    delay_step_sec: float
    rate_limit_divisor: int
    rate_limit_delay_multiplier: float
    recovery_threshold: int
    recovery_step_multiplier: float
    failure_rate_threshold: float


@dataclass(frozen=True)
class KeyExportSnapshot:
    """
    Immutable snapshot record representing a single API key's current state
    for export to NDJSON files.

    This dataclass is used by ``KeyInventoryExporter`` to build a lightweight
    representation of each key's status for backup, audit, and monitoring purposes.

    Fields:
        key_id: The database primary key of the API key.
        key_prefix: The first 10 characters of the key value (for safe identification).
        model_name: The model name associated with this key-status pair.
        status: The current status string (e.g., "valid", "rate_limited").
        next_check_time: ISO 8601 timestamp of the next scheduled health check.
    """

    key_id: int
    key_prefix: str
    model_name: str
    status: str
    next_check_time: str


@dataclass(frozen=True)
class DatabaseTableHealth:
    """
    Health statistics for a single user table from ``pg_stat_user_tables``.

    Captures the live/dead tuple counts and the most recent vacuum/analyze
    timestamps. The ``dead_tuple_ratio`` is pre-computed by the database layer
    to avoid division-by-zero errors.

    Fields:
        table_name: The fully-qualified table name (schema.table).
        n_dead_tup: Estimated number of dead (obsolete) rows.
        n_live_tup: Estimated number of live rows.
        last_vacuum: Timestamp of the last manual vacuum on this table,
            or ``None`` if never vacuumed.
        last_analyze: Timestamp of the last manual analyze on this table,
            or ``None`` if never analyzed.
        dead_tuple_ratio: Ratio of dead to total tuples (``n_dead_tup / (n_dead_tup + n_live_tup)``).
            Returns ``0.0`` when the table is empty.
    """

    table_name: str
    n_dead_tup: int
    n_live_tup: int
    last_vacuum: datetime | None
    last_analyze: datetime | None
    dead_tuple_ratio: float
