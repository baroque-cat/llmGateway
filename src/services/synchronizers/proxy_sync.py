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
    A concrete implementation of IResourceSyncer for synchronizing proxies for stealth mode.
    """

    def sync(self, config: Config, db_path: str):
        """
        Performs a full synchronization cycle for proxies.

        It iterates through all providers, checks if stealth mode is enabled,
        reads their proxy list from disk, and syncs them with the database.
        """
        logger.info("Starting proxy synchronization cycle...")

        for provider_name, provider_config in config.providers.items():
            if not provider_config.enabled:
                logger.debug(f"Provider '{provider_name}' is disabled. Skipping proxy sync.")
                continue

            # The logic here will depend on the final config structure.
            # Assuming a structure like: proxy_config.mode == "stealth"
            # For now, we use the existing structure for simplicity.
            if not provider_config.proxy_config.enabled or not provider_config.proxy_config.proxy_list_path:
                logger.debug(f"Stealth mode is not enabled or proxy_list_path is not set for '{provider_name}'. Skipping.")
                continue

            logger.info(f"Syncing proxies for provider: '{provider_name}'")

            proxies_from_file = _read_proxies_from_file(provider_config.proxy_config.proxy_list_path)
            if not proxies_from_file:
                logger.warning(f"No proxies found in file '{provider_config.proxy_config.proxy_list_path}' for provider '{provider_name}'.")

            # TODO: Implement the corresponding database function.
            # This function will need to:
            # 1. Add new proxy addresses to the global 'proxies' table.
            # 2. Add entries to the 'provider_proxy_status' table, linking the provider
            #    with the proxies from the file.
            # 3. Handle removal of proxies that are no longer in the file for this provider.
            # database.sync_proxies_for_provider(
            #     db_path=db_path,
            #     provider_name=provider_name,
            #     proxies_from_file=proxies_from_file
            # )
            logger.info(f"Database sync for proxies of provider '{provider_name}' is not yet implemented. Found {len(proxies_from_file)} proxies.")

        logger.info("Proxy synchronization cycle finished.")
