# src/services/synchronizers/proxy_sync.py

import os
import logging
from typing import Set

from src.config.schemas import Config
from src.core.types import IResourceSyncer
from src.db import database

logger = logging.getLogger(__name__)


def _read_proxies_from_file(path: str) -> Set[str]:
    """
    Reads proxy addresses from a specified file, one per line.

    Args:
        path: The path to the file containing proxy addresses.

    Returns:
        A set of unique, non-empty proxy strings.
    """
    if not os.path.exists(path) or not os.path.isfile(path):
        logger.warning(f"Proxy list file not found or is not a file: '{path}'. Skipping.")
        return set()

    all_proxies: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                proxy = line.strip()
                if proxy and not proxy.startswith('#'): # Ignore empty lines and comments
                    all_proxies.add(proxy)
    except Exception as e:
        logger.error(f"Failed to read or parse proxy file '{path}': {e}")

    return all_proxies


class ProxySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing proxies.
    This syncer specifically targets providers configured to use 'stealth' mode.
    """

    def sync(self, config: Config, db_path: str):
        """
        Performs a full synchronization cycle for proxies.

        It iterates through all providers, checks if 'stealth' proxy mode is enabled,
        reads their proxy list from disk, and syncs them with the database. Providers
        using 'none' or 'static' modes are ignored by this syncer.
        """
        logger.info("Starting proxy synchronization cycle...")

        for provider_name, provider_config in config.providers.items():
            try:
                if not provider_config.enabled:
                    logger.debug(f"Provider '{provider_name}' is disabled. Skipping proxy sync.")
                    continue

                proxy_conf = provider_config.proxy_config
                
                # This is the core logic fix: we only act if the mode is 'stealth'.
                if proxy_conf.mode != 'stealth':
                    logger.debug(
                        f"Provider '{provider_name}' is not in 'stealth' mode (mode: '{proxy_conf.mode}'). "
                        "Skipping proxy pool sync."
                    )
                    continue

                # The config validator should ensure this path exists if mode is 'stealth',
                # but we check again for robustness.
                if not proxy_conf.pool_list_path:
                    logger.warning(
                        f"Provider '{provider_name}' is in 'stealth' mode but 'pool_list_path' is not set. "
                        "Cannot sync proxies."
                    )
                    continue

                logger.info(f"Syncing proxies for provider '{provider_name}' (stealth mode).")

                proxies_from_file = _read_proxies_from_file(proxy_conf.pool_list_path)
                logger.info(f"Found {len(proxies_from_file)} unique proxies in '{proxy_conf.pool_list_path}' for provider '{provider_name}'.")
                
                database.sync_proxies_for_provider(
                    db_path=db_path,
                    provider_name=provider_name,
                    proxies_from_file=proxies_from_file
                )
            
            except Exception as e:
                # Isolate failures: an error with one provider should not stop the entire sync cycle.
                logger.error(f"An unexpected error occurred while syncing proxies for provider '{provider_name}': {e}", exc_info=True)


        logger.info("Proxy synchronization cycle finished.")

