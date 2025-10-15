# src/services/synchronizers/key_sync.py

import os
import re
import logging
from typing import Set, List

from src.config.schemas import Config
from src.core.types import IResourceSyncer
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def _read_keys_from_directory(path: str) -> Set[str]:
    """
    Reads all files in a specified directory, extracts API keys, and returns them as a unique set.
    This function performs synchronous file I/O, which is acceptable for this periodic task.
    """
    if not os.path.exists(path) or not os.path.isdir(path):
        logger.warning(f"Key directory not found or is not a directory: '{path}'. Skipping.")
        return set()

    all_keys: Set[str] = set()
    try:
        for filename in os.listdir(path):
            filepath = os.path.join(path, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        keys_in_file = re.split(r'[\s,]+', content)
                        cleaned_keys = {key for key in keys_in_file if key}
                        all_keys.update(cleaned_keys)
                except Exception as e:
                    logger.error(f"Failed to read or parse key file '{filepath}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to list files in directory '{path}': {e}", exc_info=True)

    return all_keys


class KeySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing API keys (Async Version).
    """

    async def sync(self, config: Config, db_manager: DatabaseManager):
        """
        Performs a full synchronization cycle for API keys using the async DatabaseManager.
        """
        logger.info("Starting API key synchronization cycle...")

        try:
            # Fetch the provider name-to-ID mapping once at the beginning for efficiency.
            provider_id_map = await db_manager.providers.get_id_map()
        except Exception as e:
            logger.critical(f"Failed to fetch provider ID map from database. Aborting key sync cycle. Error: {e}", exc_info=True)
            return

        for provider_name, provider_config in config.providers.items():
            try:
                if not provider_config.enabled:
                    logger.debug(f"Provider '{provider_name}' is disabled in config. Skipping key sync.")
                    continue

                if not provider_config.keys_path:
                    logger.warning(f"No 'keys_path' configured for provider '{provider_name}'. Skipping key sync.")
                    continue

                provider_id = provider_id_map.get(provider_name)
                if provider_id is None:
                    logger.error(f"Provider '{provider_name}' not found in the database. It may not have been synced yet. Skipping.")
                    continue
                
                logger.info(f"Syncing keys for provider: '{provider_name}' (ID: {provider_id})")

                # Step 1: Read keys from the specified directory (sync I/O).
                keys_from_file = _read_keys_from_directory(provider_config.keys_path)
                logger.info(f"Found {len(keys_from_file)} unique keys in '{provider_config.keys_path}' for provider '{provider_name}'.")

                # Step 2: Aggregate all models for this provider from the config.
                all_provider_models: List[str] = [
                    model
                    for model_list in provider_config.models.values()
                    for model in model_list
                ]

                # Step 3: Call the async database repository method to perform synchronization.
                await db_manager.keys.sync(
                    provider_name=provider_name,
                    keys_from_file=keys_from_file,
                    provider_id=provider_id,
                    provider_models=all_provider_models
                )
            except Exception as e:
                # Isolate failures to prevent one provider from halting the entire sync process.
                logger.error(f"An unexpected error occurred while syncing keys for provider '{provider_name}': {e}", exc_info=True)

        logger.info("API key synchronization cycle finished.")
