# src/services/gateway_cache.py

import asyncio
import collections
import logging
from typing import Deque, Tuple, DefaultDict

from src.core.accessor import ConfigAccessor
from src.core.constants import ALL_MODELS_MARKER
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
        self._auth_token_map: dict[str, str] = {}

        # Cache now stores tuples of (key_id, key_value)
        # to enable the "fast feedback loop" in the gateway service.
        self._key_pool: dict[str, collections.deque[tuple[int, str]]] = (
            collections.defaultdict(collections.deque)
        )

        # A lock to prevent race conditions during concurrent cache modifications.
        # This lock must be used by ALL methods that write to _key_pool.
        self._refresh_lock = asyncio.Lock()

    def _populate_auth_map(self) -> None:
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

        logger.info(
            f"Authentication token cache populated with {len(self._auth_token_map)} tokens."
        )

    async def refresh_key_pool(self) -> None:
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
                valid_keys_data = (
                    await self.db_manager.keys.get_all_valid_keys_for_caching()
                )

                # 2. Build a new key pool in a temporary variable.
                new_key_pool: DefaultDict[str, Deque[Tuple[int, str]]] = collections.defaultdict(collections.deque)
                for record in valid_keys_data:
                    key_id = record["key_id"]
                    provider_name = record["provider_name"]
                    model_name = record["model_name"]
                    key_value = record["key_value"]
                    pool_key = f"{provider_name}:{model_name}"

                    new_key_pool[pool_key].append((key_id, key_value))

                # 3. Atomically replace the old pool with the new one.
                self._key_pool = new_key_pool

                total_keys = sum(len(q) for q in self._key_pool.values())
                logger.info(
                    f"Key pool cache refreshed successfully. Loaded {total_keys} keys across {len(self._key_pool)} pools."
                )

            except Exception as e:
                logger.critical(
                    "Failed to refresh key pool cache due to a database error.",
                    exc_info=e,
                )

    async def populate_caches(self) -> None:
        """
        Performs the initial population of all caches.
        This should be called once when the gateway service starts.
        """
        self._populate_auth_map()
        await self.refresh_key_pool()

    def get_instance_name_by_token(self, token: str) -> str | None:
        """
        Retrieves the provider instance name associated with a gateway access token.

        Args:
            token: The gateway access token from the request headers.

        Returns:
            The provider instance name if the token is valid, otherwise None.
        """
        return self._auth_token_map.get(token)

    def get_key_from_pool(
        self, provider_name: str, model_name: str
    ) -> tuple[int, str] | None:
        """
        Retrieves one available API key from the specified pool and rotates it.

        This operation is performed in O(1) time and is NOT locked to ensure
        maximum performance for read operations. `deque` operations are atomic.

        Args:
            provider_name: The name of the provider instance.
            model_name: The name of the requested model.

        Returns:
            A tuple of (key_id, key_value) if a key is available, otherwise None.
        """
        # Check if provider has shared_key_status enabled
        provider_config = self.accessor.get_provider(provider_name)
        actual_model_name = model_name

        if provider_config and provider_config.shared_key_status:
            # For shared keys, look in the virtual model pool
            pool_key = f"{provider_name}:{ALL_MODELS_MARKER}"
        else:
            pool_key = f"{provider_name}:{model_name}"

        key_queue = self._key_pool.get(pool_key)

        if key_queue:
            try:
                # Get a key tuple from the left (front) of the deque.
                key_info = key_queue.popleft()
                # Append it to the right (back) to rotate it.
                key_queue.append(key_info)
                return key_info
            except IndexError:
                # This can happen in a rare race condition if the pool becomes empty
                # between the 'if' check and 'popleft' because of a concurrent removal.
                return None

        return None

    # --- REFACTORED: Method is now aware of shared_key_status ---
    async def remove_key_from_pool(
        self, provider_name: str, model_name: str, key_id: int
    ) -> None:
        """
        Immediately removes a specific key from the live key pool cache.

        If the provider has 'shared_key_status' enabled, this method will
        remove the key from the virtual model pool (ALL_MODELS_MARKER).
        Otherwise, it removes the key only from the specific model's pool.
        This is a write operation and is protected by a lock.

        Args:
            provider_name: The name of the provider instance.
            model_name: The name of the model that triggered the failure.
            key_id: The database ID of the key to remove.
        """
        async with self._refresh_lock:
            provider_config = self.accessor.get_provider(provider_name)

            # --- NEW: Logic to decide removal strategy ---
            if provider_config and provider_config.shared_key_status:
                # Remove the key only from the virtual model pool
                logger.info(
                    f"Removing shared key_id {key_id} from virtual pool '{provider_name}:{ALL_MODELS_MARKER}' for provider '{provider_name}'."
                )
                pool_key = f"{provider_name}:{ALL_MODELS_MARKER}"
                self._remove_from_single_pool(pool_key, key_id)
            else:
                # Granular removal: remove the key only from the specific pool.
                pool_key = f"{provider_name}:{model_name}"
                self._remove_from_single_pool(pool_key, key_id)

    def _remove_from_single_pool(self, pool_key: str, key_id: int) -> None:
        """
        A private helper to perform the removal logic on a single key pool.
        This avoids code duplication.
        """
        key_queue = self._key_pool.get(pool_key)

        if not key_queue:
            return  # The pool is already empty or doesn't exist.

        initial_size = len(key_queue)

        # Re-create the deque, excluding the key with the matching ID.
        new_queue = collections.deque([info for info in key_queue if info[0] != key_id])

        if len(new_queue) < initial_size:
            self._key_pool[pool_key] = new_queue
            logger.info(
                f"Removed failed key_id {key_id} from live cache pool '{pool_key}'. "
                f"Pool size changed from {initial_size} to {len(new_queue)}."
            )
        else:
            # This is not an error, just means the key was already removed by another coroutine.
            logger.debug(
                f"Attempted to remove key_id {key_id} from pool '{pool_key}', but it was not found."
            )
