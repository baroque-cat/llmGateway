# src/core/types.py

"""
Core Types - Abstract Interfaces and Protocols.

This module defines abstract base classes and interfaces that establish
the fundamental contracts for different components within the system,
ensuring a modular and extensible architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

import httpx

# Import the necessary data models and dependencies for type hints.
from src.core.accessor import ConfigAccessor
from src.core.models import CheckResult, DatabaseTableHealth, RequestDetails

if TYPE_CHECKING:
    from src.db.database import DatabaseManager

# --- TypedDicts for Background Worker's Synchronization State ---
# These structures provide type safety for the data collected during the
# "Read Phase" of the background worker's synchronization cycle.


class ProviderKeyState(TypedDict):
    """Represents the desired state for keys of a single provider."""

    keys_from_files: set[str]
    models_from_config: list[str]
    file_map: dict[str, float]


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
    ) -> tuple[httpx.Response, CheckResult, bytes | None]:
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
            A 3-tuple of ``(httpx.Response, CheckResult, bytes | None)``.
            The third element is the pre-read upstream body when debug_mode
            or error_parsing triggered ``aread()``, otherwise ``None``.
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


class IKeyInventoryExporter(ABC):
    """
    Contract for exporting the current state of API keys to NDJSON files.

    Implementations are responsible for querying the database and writing
    NDJSON files in the ``data/<provider_name>/`` directory hierarchy.

    This ABC lives in the core layer to keep the contract free of database
    and service implementation details.  The ``db_manager`` parameter uses a
    ``TYPE_CHECKING`` guard so the core does not import from ``src.db`` at
    runtime.
    """

    @abstractmethod
    async def export_snapshot(
        self, provider_name: str, db_manager: DatabaseManager
    ) -> None:
        """Export all keys for a provider to ``data/<name>/all_keys.ndjson``.

        Queries the database for every API key belonging to *provider_name*,
        constructs ``KeyExportSnapshot`` records, and writes them as an
        NDJSON file via ``write_atomic_ndjson``.

        Args:
            provider_name: The unique instance name of the provider.
            db_manager: The database manager for executing queries.
        """
        raise NotImplementedError

    @abstractmethod
    async def export_inventory(
        self, provider_name: str, db_manager: DatabaseManager, statuses: list[str]
    ) -> None:
        """Export keys grouped by status to ``data/<name>/<status>/keys.ndjson``.

        For each status in *statuses*, queries the database for keys with
        that status and writes them to a separate NDJSON file.

        Args:
            provider_name: The unique instance name of the provider.
            db_manager: The database manager for executing queries.
            statuses: List of status strings to export as separate groups.
        """
        raise NotImplementedError


class IKeyPurger(ABC):
    """
    Contract for purging stopped API keys and deleted provider data.

    Implementations are responsible for safely deleting keys that have been
    in a permanently stopped state, and for removing all key data when a
    provider is removed from configuration.
    """

    @abstractmethod
    async def purge_provider(
        self, provider_id: int, db_manager: DatabaseManager
    ) -> int:
        """Delete all key data for a provider that was removed from configuration.

        Args:
            provider_id: The database ID of the provider to purge.
            db_manager: The database manager for executing queries.

        Returns:
            The number of API keys deleted (via CASCADE).
        """
        raise NotImplementedError

    @abstractmethod
    async def purge_stopped_keys(
        self,
        provider_name: str,
        provider_id: int,
        cutoff: datetime,
        db_manager: DatabaseManager,
    ) -> int:
        """Delete keys that have been in a stopped state beyond the cutoff.

        A key is considered stopped when its ``failing_since`` is before
        *cutoff* and its ``next_check_time`` is far in the future
        (more than 300 days from now), indicating the system has given up
        on re-checking it.

        Args:
            provider_name: The unique instance name of the provider.
            provider_id: The database ID of the provider.
            cutoff: Keys with ``failing_since`` before this UTC datetime
                are eligible for deletion.
            db_manager: The database manager for executing queries.

        Returns:
            The number of API keys deleted.
        """
        raise NotImplementedError


class IDatabaseMaintainer(ABC):
    """
    Contract for database maintenance operations based on health metrics.

    Implementations query ``pg_stat_user_tables`` and perform conditional
    ``VACUUM ANALYZE`` operations on tables whose dead-tuple ratio exceeds
    a configured threshold.
    """

    @abstractmethod
    async def get_table_health(
        self, db_manager: DatabaseManager
    ) -> list[DatabaseTableHealth]:
        """Retrieve health statistics for all user tables.

        Queries ``pg_stat_user_tables`` and returns a list of
        ``DatabaseTableHealth`` records, one per table.

        Args:
            db_manager: The database manager for executing queries.

        Returns:
            A list of health records.  May be empty if the database
            version does not support ``pg_stat_user_tables`` or if
            the user lacks the required permissions.
        """
        raise NotImplementedError

    @abstractmethod
    async def run_conditional_vacuum(
        self, tables: list[DatabaseTableHealth], db_manager: DatabaseManager
    ) -> int:
        """Run ``VACUUM ANALYZE`` on tables that exceed the dead tuple threshold.

        Iterates over *tables*, calls ``should_vacuum()`` for each one
        against the configured threshold, and issues ``VACUUM ANALYZE``
        for qualifying tables.

        Args:
            tables: Health records from ``get_table_health()``.
            db_manager: The database manager for executing queries.

        Returns:
            The number of tables that were vacuumed.
        """
        raise NotImplementedError
