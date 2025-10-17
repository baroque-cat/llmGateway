import logging
import asyncio
from typing import Dict

import httpx

from src.config.schemas import Config, ProviderConfig


class HttpClientFactory:
    """
    A factory for creating, caching, and managing httpx.AsyncClient instances.

    This class ensures that for a given configuration (e.g., a specific proxy URL
    or no proxy at all), only one client instance is created and reused. This
    optimizes resource usage by leveraging httpx's connection pooling.

    It is designed to be thread-safe in an async context by using locks to
    prevent race conditions during client creation.
    """

    def __init__(self, config: Config):
        """
        Initializes the HttpClientFactory.

        Args:
            config: The loaded application configuration object. This is a form
                    of dependency injection, making the factory testable and
                    decoupled from the configuration loading mechanism.
        """
        # --- Step 1: Initialization from Plan ---
        # This implements the constructor logic from our plan.
        # It sets up the logger, the client cache, and the lock dictionary.
        # Using dependency injection for `config` makes the class robust and testable.
        self.config: Config = config
        self.logger: logging.Logger = logging.getLogger(__name__)
        
        # The cache to store long-lived client instances.
        # The key is a unique identifier for the client's configuration (e.g., proxy URL).
        self._clients: Dict[str, httpx.AsyncClient] = {}
        
        # A dictionary to hold asyncio.Lock objects, one for each potential cache key.
        # This prevents race conditions where multiple coroutines try to create the
        # same client simultaneously.
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_cache_key_for_provider(self, provider_config: ProviderConfig) -> str:
        """
        Determines the unique cache key based on the provider's proxy configuration.
        """
        # --- Step 2: Cache Key Logic from Plan ---
        # This private helper method implements the cache key determination logic.
        # It's separated for clarity and reusability.
        proxy_config = provider_config.proxy_config
        if proxy_config.mode == 'none':
            # A constant key for all direct connections.
            return "__none__"
        elif proxy_config.mode == 'static':
            # The proxy URL itself is the unique key. This ensures providers
            # sharing the same static proxy also share the same client instance.
            if not proxy_config.static_url:
                raise ValueError("Static proxy mode requires a 'static_url' to be set.")
            return proxy_config.static_url
        else:
            # Future-proofing for 'stealth' mode or other modes.
            raise NotImplementedError(f"Proxy mode '{proxy_config.mode}' is not supported by the factory yet.")

    async def get_client_for_provider(self, provider_name: str) -> httpx.AsyncClient:
        """
        Retrieves or creates an httpx.AsyncClient for a specific provider.

        It uses an internal cache to avoid recreating clients. If a client for the
        provider's configuration doesn't exist, it creates a new one, enables
        HTTP/2, and configures proxies as needed.

        Args:
            provider_name: The name of the provider instance as defined in the config.

        Returns:
            An httpx.AsyncClient instance ready for use.
        
        Raises:
            KeyError: If the provider_name is not found in the configuration.
        """
        # --- Step 3: Main Logic from Plan ---
        # This is the core method, implementing steps 1 through 6 of the plan.
        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            raise KeyError(f"Configuration for provider '{provider_name}' not found.")

        cache_key = self._get_cache_key_for_provider(provider_config)

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

            self.logger.info(f"Cache miss for key '{cache_key}'. Creating new HTTP/2 client...")

            proxy_url = None
            if provider_config.proxy_config.mode == 'static':
                proxy_url = provider_config.proxy_config.static_url

            # --- Step 4: Client Creation from Plan ---
            # Here we create the client as planned, enabling HTTP/2 and setting the proxy if needed.
            # This directly follows httpx documentation for client instantiation [24, 25, 29].
            try:
                client = httpx.AsyncClient(
                    http2=True,      # Enable HTTP/2 for better performance.
                    proxy=proxy_url  # Set the proxy URL if one is required.
                )
                
                self._clients[cache_key] = client
                self.logger.info(f"Successfully created and cached new client for key '{cache_key}'.")
                return client
            except Exception as e:
                self.logger.critical(f"Failed to create httpx.AsyncClient for key '{cache_key}': {e}", exc_info=True)
                # Re-raise the exception so the caller knows something went wrong.
                raise

    async def close_all(self):
        """
        Gracefully closes all cached httpx.AsyncClient instances.

        This should be called during application shutdown to ensure all
        underlying network connections are properly terminated.
        """
        # --- Step 5: Shutdown Logic from Plan ---
        # This implements the graceful shutdown. Using asyncio.gather
        # is the most efficient way to close many async resources concurrently.
        if not self._clients:
            self.logger.info("No active HTTP clients to close.")
            return

        self.logger.info(f"Closing {len(self._clients)} cached HTTP client(s)...")
        
        # Concurrently close all clients.
        closing_tasks = [client.aclose() for client in self._clients.values()]
        await asyncio.gather(*closing_tasks, return_exceptions=True)
        
        self._clients.clear()
        self._locks.clear()
        self.logger.info("All HTTP clients have been closed and cache has been cleared.")

