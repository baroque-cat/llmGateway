# src/services/synchronizers/proxy_sync.py

import os
import logging
from typing import Set

from src.config.schemas import Config
from src.core.types import IResourceSyncer
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def _read_proxies_from_file(path: str) -> Set[str]:
    """
    Reads proxy addresses from a specified file, one per line.
    This function performs synchronous file I/O.
    """
    if not os.path.exists(path) or not os.path.isfile(path):
        logger.warning(f"Proxy list file not found or is not a file: '{path}'. Skipping.")
        return set()

    all_proxies: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                proxy = line.strip()
                if proxy and not proxy.startswith('#'):
                    all_proxies.add(proxy)
    except Exception as e:
        logger.error(f"Failed to read or parse proxy file '{path}': {e}")

    return all_proxies


class ProxySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing proxies (Async Version).
    This syncer targets providers configured to use 'stealth' mode.
    """

    async def sync(self, config: Config, db_manager: DatabaseManager):
        """
        Performs a full synchronization cycle for proxies using the async DatabaseManager.
        """
        logger.info("Starting proxy synchronization cycle...")
        
        try:
            provider_id_map = await db_manager.providers.get_id_map()
        except Exception as e:
            logger.critical(f"Failed to fetch provider ID map from database. Aborting proxy sync cycle. Error: {e}", exc_info=True)
            return

        for provider_name, provider_config in config.providers.items():
            try:
                if not provider_config.enabled:
                    logger.debug(f"Provider '{provider_name}' is disabled. Skipping proxy sync.")
                    continue

                proxy_conf = provider_config.proxy_config
                
                if proxy_conf.mode != 'stealth':
                    continue

                if not proxy_conf.pool_list_path:
                    logger.warning(
                        f"Provider '{provider_name}' is in 'stealth' mode but 'pool_list_path' is not set. Cannot sync proxies."
                    )
                    continue
                
                provider_id = provider_id_map.get(provider_name)
                if provider_id is None:
                    logger.error(f"Provider '{provider_name}' not found in the database. Skipping proxy sync.")
                    continue

                logger.info(f"Syncing proxies for provider '{provider_name}' (ID: {provider_id}, stealth mode).")

                proxies_from_file = _read_proxies_from_file(proxy_conf.pool_list_path)
                logger.info(f"Found {len(proxies_from_file)} unique proxies in '{proxy_conf.pool_list_path}' for provider '{provider_name}'.")
                
                # The actual sync logic will be in the repository method.
                await db_manager.proxies.sync(
                    provider_name=provider_name,
                    proxies_from_file=proxies_from_file,
                    provider_id=provider_id
                )
            
            except Exception as e:
                logger.error(f"An unexpected error occurred while syncing proxies for provider '{provider_name}': {e}", exc_info=True)

        logger.info("Proxy synchronization cycle finished.")
