# src/services/gateway_cache.py

import logging
import asyncio
import collections
from typing import Dict, Optional, Deque

from src.core.accessor import ConfigAccessor
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

class GatewayCache:
    """
    Manages high-performance in-memory caches for the API Gateway.
    
    This class encapsulates the logic for caching authentication tokens and
    pools of available API keys. It is designed to be populated at startup
    and periodically refreshed, providing near-instantaneous data access
    to the gateway service during request processing, thus avoiding direct
    database calls in the hot path.
    """
    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the GatewayCache with necessary dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        self.accessor = accessor
        self.db_manager = db_manager
        
        # Cache for mapping gateway access tokens to provider instance names.
        self._auth_token_map: Dict[str, str] = {}
        
        # Cache for pools of valid API keys, grouped by provider and model.
        # The key is a composite string "provider_name:model_name".
        # collections.deque is used for efficient O(1) pops from the left.
        self._key_pool: Dict[str, Deque[str]] = collections.defaultdict(collections.deque)
        
        # A lock to prevent race conditions during concurrent cache refresh operations.
        self._refresh_lock = asyncio.Lock()

    def _populate_auth_map(self):
        """
        Populates the authentication token cache from the configuration.
        This is a synchronous operation performed once at startup.
        """
        logger.info("Populating authentication token cache...")
        self._auth_token_map.clear()
        
        enabled_providers = self.accessor.get_enabled_providers()
        for name, config in enabled_providers.items():
            token = config.access_control.gateway_access_token
            if token:
                if token in self._auth_token_map:
                    # The validator should prevent this, but this is a safeguard.
                    logger.warning(
                        f"Duplicate gateway access token '{token}' found for providers "
                        f"'{self._auth_token_map[token]}' and '{name}'. The latter will be ignored."
                    )
                else:
                    self._auth_token_map[token] = name
        
        logger.info(f"Authentication token cache populated with {len(self._auth_token_map)} tokens.")

    async def refresh_key_pool(self):
        """
        Asynchronously refreshes the API key pool from the database.
        
        This method fetches all currently valid keys and rebuilds the
        in-memory key pool. It is designed to be called periodically.
        The operation is protected by a lock to ensure atomicity.
        """
        async with self._refresh_lock:
            logger.info("Refreshing key pool cache from database...")
            try:
                # 1. Fetch all valid keys in a single, efficient query.
                valid_keys_data = await self.db_manager.keys.get_all_valid_keys_for_caching()
                
                # 2. Build a new key pool in a temporary variable.
                new_key_pool = collections.defaultdict(collections.deque)
                for record in valid_keys_data:
                    provider_name = record['provider_name']
                    model_name = record['model_name']
                    key_value = record['key_value']
                    pool_key = f"{provider_name}:{model_name}"
                    new_key_pool[pool_key].append(key_value)
                
                # 3. Atomically replace the old pool with the new one.
                self._key_pool = new_key_pool
                
                total_keys = sum(len(q) for q in self._key_pool.values())
                logger.info(f"Key pool cache refreshed successfully. Loaded {total_keys} keys across {len(self._key_pool)} pools.")

            except Exception as e:
                logger.critical("Failed to refresh key pool cache due to a database error.", exc_info=e)

    async def populate_caches(self):
        """
        Performs the initial population of all caches.
        This should be called once when the gateway service starts.
        """
        self._populate_auth_map()
        await self.refresh_key_pool()

    def get_instance_name_by_token(self, token: str) -> Optional[str]:
        """
        Retrieves the provider instance name associated with a gateway access token.
        
        Args:
            token: The gateway access token from the request headers.
            
        Returns:
            The provider instance name if the token is valid, otherwise None.
        """
        return self._auth_token_map.get(token)

    def get_key_from_pool(self, provider_name: str, model_name: str) -> Optional[str]:
        """
        Retrieves and removes one available API key from the specified pool.
        
        This operation is performed in O(1) time. If a key is used, it is
        rotated to the back of the queue to ensure fair usage.
        
        Args:
            provider_name: The name of the provider instance.
            model_name: The name of the requested model.
            
        Returns:
            An API key string if one is available, otherwise None.
        """
        pool_key = f"{provider_name}:{model_name}"
        
        key_queue = self._key_pool.get(pool_key)
        
        if key_queue:
            try:
                # Get a key from the left (front) of the deque.
                key = key_queue.popleft()
                # Append it to the right (back) to rotate it.
                key_queue.append(key)
                return key
            except IndexError:
                # This can happen in a rare race condition if the pool becomes empty
                # between the 'if' check and 'popleft'.
                return None
        
        return None
