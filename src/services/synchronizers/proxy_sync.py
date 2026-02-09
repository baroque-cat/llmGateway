# src/services/synchronizers/proxy_sync.py

import logging
import os
import re

from src.core.accessor import ConfigAccessor

# REFACTORED: Import new TypedDict for state representation.
from src.core.interfaces import IResourceSyncer, ProviderProxyState
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def read_proxies_from_directory(path: str) -> set[str]:
    """
    Reads all files in a specified directory, extracts proxy URLs, and returns them as a unique set.
    This helper function is now intended to be called by the background worker during the "Read Phase".
    """
    if not os.path.exists(path) or not os.path.isdir(path):
        logger.warning(
            f"Proxy directory not found or is not a directory: '{path}'. Skipping."
        )
        return set()

    all_proxies: set[str] = set()
    try:
        for filename in os.listdir(path):
            filepath = os.path.join(path, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, encoding="utf-8") as f:
                        content = f.read()
                        # Proxies are usually one per line, but we support space/comma separation too.
                        proxies_in_file = re.split(r"[\s,]+", content)
                        # A simple validation to filter out empty strings. More robust validation
                        # could be added here if needed (e.g., regex for proxy format).
                        cleaned_proxies = {
                            p for p in proxies_in_file if p and "://" in p
                        }
                        all_proxies.update(cleaned_proxies)
                except Exception as e:
                    logger.error(
                        f"Failed to read or parse proxy file '{filepath}': {e}",
                        exc_info=True,
                    )
    except Exception as e:
        logger.error(f"Failed to list files in directory '{path}': {e}", exc_info=True)

    return all_proxies


class ProxySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing proxy lists.
    This class implements the "apply_state" pattern.
    """

    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the ProxySyncer with its required dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        self.accessor = accessor
        self.db_manager = db_manager

    # REFACTORED: The old 'sync' method is replaced by 'apply_state'.
    async def apply_state(
        self,
        provider_id_map: dict[str, int],
        desired_state: dict[str, ProviderProxyState],
    ) -> None:
        """
        Performs a full synchronization for proxies by applying the desired state to the database.

        Args:
            provider_id_map: A mapping from provider name to its database ID.
            desired_proxy_state: A dictionary where keys are provider names and values
                                 are ProviderProxyState objects.
        """
        logger.info("Applying desired proxy state to the database...")

        if not desired_state:
            logger.info(
                "No proxy state to apply. Proxy synchronization cycle finished."
            )
            return

        for provider_name, state in desired_state.items():
            try:
                provider_id = provider_id_map.get(provider_name)
                if provider_id is None:
                    logger.error(
                        f"Provider '{provider_name}' not found in the ID map. Skipping proxy sync for this provider."
                    )
                    continue

                proxies_from_file = state["proxies_from_files"]

                logger.info(
                    f"Applying state for provider '{provider_name}' (ID: {provider_id}): "
                    f"{len(proxies_from_file)} proxies."
                )

                # IMPORTANT: This call assumes that `db_manager.proxies.sync` has been implemented
                # to take the provider ID and the set of proxies from the file, and then
                # reconcile the state in the `proxies` and `provider_proxy_status` tables.
                await self.db_manager.proxies.sync(
                    provider_name=provider_name,
                    provider_id=provider_id,
                    proxies_from_file=proxies_from_file,
                )
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred while applying proxy state for provider '{provider_name}': {e}",
                    exc_info=True,
                )

        logger.info("Finished applying desired proxy state.")
