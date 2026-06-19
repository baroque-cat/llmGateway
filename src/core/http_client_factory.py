# src/core/http_client_factory.py

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

# REFACTORED: Import ConfigAccessor instead of the raw Config schema.
from src.config.logging_config import get_trace_handler
from src.core.accessor import ConfigAccessor
from src.core.http2 import CapacityAwareHttp2Transport


class HttpClientFactory:
    """
    A factory for creating, caching, and managing httpx.AsyncClient instances.

    This class ensures that for a given configuration (e.g., a specific proxy URL
    or no proxy at all), only one client instance is created and reused. This
    optimizes resource usage by leveraging httpx's connection pooling.

    It is designed to be thread-safe in an async context by using locks to
    prevent race conditions during client creation.
    """

    # REFACTORED: The constructor now accepts ConfigAccessor for dependency injection.
    def __init__(self, accessor: ConfigAccessor):
        """
        Initializes the HttpClientFactory.

        Args:
            accessor: An instance of ConfigAccessor to safely access configuration values.
        """
        self.accessor: ConfigAccessor = accessor
        self.logger: logging.Logger = logging.getLogger(__name__)

        # Read global HTTP client config for pool limits and HTTP/2 toggle.
        http_config = accessor.get_http_client_config()
        self._http2_enabled: bool = http_config.http2
        self._pool_config = http_config.pool
        self._pool_health_log_interval_sec: int = (
            http_config.pool_health_log_interval_sec
        )

        # Trace handler for per-request httpx trace events.
        self._trace_handler: Callable[[dict[str, Any]], None] | None = (
            get_trace_handler()
        )

        # The cache to store long-lived client instances.
        # The key is a unique identifier for the client's configuration (e.g., proxy URL).
        self._clients: dict[str, httpx.AsyncClient] = {}

        # A dictionary to hold asyncio.Lock objects, one for each potential cache key.
        # This prevents race conditions where multiple coroutines try to create the
        # same client simultaneously.
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_cache_key_for_proxy(self, provider_name: str) -> str:
        """
        Determines the unique cache key based on the provider's proxy configuration.
        """
        # REFACTORED: Use accessor to get proxy config
        proxy_config = self.accessor.get_proxy_config(provider_name)
        if not proxy_config:
            raise ValueError(f"Proxy config not found for provider '{provider_name}'")

        if proxy_config.mode == "none":
            # A constant key for all direct connections.
            return "__none__"
        elif proxy_config.mode == "static":
            # The proxy URL itself is the unique key. This ensures providers
            # sharing the same static proxy also share the same client instance.
            if not proxy_config.static_url:
                raise ValueError("Static proxy mode requires a 'static_url' to be set.")
            return proxy_config.static_url
        raise ValueError(
            f"Proxy mode '{proxy_config.mode}' is not supported by the factory yet."
        )

    def _get_cache_key_for_provider(self, provider_name: str) -> str:
        """
        Determines the httpx.AsyncClient cache key for a provider.

        If the provider has ``dedicated_http_client=True``, returns the instance name
        (unique dedicated client for this instance). Otherwise the key is determined
        via ``_get_cache_key_for_proxy`` — proxy-based caching (shared client
        for providers with the same proxy mode).

        Args:
            provider_name: The provider instance name from the configuration.

        Returns:
            str: The cache key for the httpx.AsyncClient.
        """
        provider = self.accessor.get_provider(provider_name)
        if provider and provider.dedicated_http_client:
            return provider_name
        return self._get_cache_key_for_proxy(provider_name)

    async def get_client_for_provider(self, provider_name: str) -> httpx.AsyncClient:
        """
        Retrieves or creates an httpx.AsyncClient for a specific provider.

        Uses an internal cache to avoid recreating clients. If the provider
        has ``dedicated_http_client=True``, a dedicated client is created with
        key = instance name (not shared with other providers). Otherwise the
        client is cached by proxy configuration (shared among providers with
        the same proxy mode).

        Args:
            provider_name: The name of the provider instance as defined in the config.

        Returns:
            An httpx.AsyncClient instance ready for use.

        Raises:
            KeyError: If the provider_name is not found in the configuration.
        """
        # Check existence first
        if not self.accessor.get_provider(provider_name):
            raise KeyError(f"Provider '{provider_name}' not found")

        cache_key = self._get_cache_key_for_provider(provider_name)

        # First, check the cache for a quick return without locking.
        if cache_key in self._clients:
            return self._clients[cache_key]

        # If not in cache, acquire a lock specific to this key to prevent race conditions.
        # setdefault is an atomic operation, ensuring only one lock is created per key.
        lock = self._locks.setdefault(cache_key, asyncio.Lock())

        async with lock:
            # Double-check the cache. Another coroutine might have created the client
            # while this one was waiting for the lock.
            if cache_key in self._clients:
                return self._clients[cache_key]

            # Create descriptive connection info for logging
            proxy_config = self.accessor.get_proxy_config(provider_name)
            if proxy_config and proxy_config.mode == "none":
                connection_desc = f"provider '{provider_name}' (direct connection)"
            elif proxy_config and proxy_config.mode == "static":
                static_url = proxy_config.static_url or "unknown"
                connection_desc = f"provider '{provider_name}' (proxy: {static_url})"
            elif proxy_config:
                connection_desc = (
                    f"provider '{provider_name}' (proxy mode: {proxy_config.mode})"
                )
            else:
                connection_desc = f"provider '{provider_name}' (proxy config not found)"

            self.logger.debug(
                f"Cache miss for {connection_desc}. Creating new HTTP/{'2' if self._http2_enabled else '1.1'} client..."
            )

            proxy_url = None
            # REFACTORED: Use accessor for proxy config
            if proxy_config and proxy_config.mode == "static":
                proxy_url = proxy_config.static_url

            try:
                limits = httpx.Limits(
                    max_connections=self._pool_config.max_connections,
                    max_keepalive_connections=self._pool_config.max_keepalive_connections,
                    keepalive_expiry=self._pool_config.keepalive_expiry,
                )
                transport = CapacityAwareHttp2Transport(
                    verify=True,
                    http1=True,
                    http2=self._http2_enabled,
                    limits=limits,
                )
                client_kwargs: dict[str, Any] = {
                    "http2": self._http2_enabled,
                    "transport": transport,
                    "proxy": proxy_url,
                    "limits": limits,
                }
                if self._trace_handler is not None:
                    client_kwargs["extensions"] = {"trace": self._trace_handler}

                client = httpx.AsyncClient(**client_kwargs)

                self._clients[cache_key] = client
                self.logger.debug(
                    f"Successfully created and cached new client for {connection_desc}."
                )
                return client
            except Exception as e:
                self.logger.critical(
                    f"Failed to create httpx.AsyncClient for key '{cache_key}': {e}",
                    exc_info=True,
                )
                # Re-raise the exception so the caller knows something went wrong.
                raise

    async def close_all(self) -> None:
        """
        Gracefully closes all cached httpx.AsyncClient instances.

        This should be called during application shutdown to ensure all
        underlying network connections are properly terminated.
        """
        if not self._clients:
            self.logger.info("No active HTTP clients to close.")
            return

        self.logger.info(f"Closing {len(self._clients)} cached HTTP client(s)...")

        # Concurrently close all clients.
        closing_tasks = [client.aclose() for client in self._clients.values()]
        await asyncio.gather(*closing_tasks, return_exceptions=True)

        self._clients.clear()
        self._locks.clear()
        self.logger.info(
            "All HTTP clients have been closed and cache has been cleared."
        )

    def get_pool_health_summary(self) -> dict[str, dict[str, int]]:
        """Return pool health summaries for all cached HTTP clients.

        Iterates over ``_clients`` and calls
        ``CapacityAwareHttp2Pool.get_health_summary()`` on each
        client's transport pool.

        Returns:
            A mapping from cache key to pool health summary dict.
            Returns an empty dict when no clients are cached.
        """
        result: dict[str, dict[str, int]] = {}
        for cache_key, client in self._clients.items():
            pool = getattr(client._transport, "_pool", None)  # type: ignore[reportPrivateUsage]
            if pool is not None and hasattr(pool, "get_health_summary"):
                result[cache_key] = pool.get_health_summary()
        return result
