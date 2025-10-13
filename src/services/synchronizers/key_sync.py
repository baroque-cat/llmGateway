# src/services/synchronizers/key_sync.py

import os
import re
import logging
from typing import Set, List

from src.config.schemas import Config
from src.core.types import IResourceSyncer
from src.db import database

# Initialize a logger for this module.
# The logger's output will be configured by the main application entry point.
logger = logging.getLogger(__name__)


def _read_keys_from_directory(path: str) -> Set[str]:
    """
    Reads all files in a specified directory, extracts API keys, and returns them as a unique set.

    This function is designed to be robust:
    - It handles various separators (spaces, commas, newlines) using regex.
    - It automatically removes duplicate keys by using a set.
    - It gracefully handles cases where the directory does not exist.

    Args:
        path: The path to the directory containing key files.

    Returns:
        A set of unique, non-empty API key strings found in the files.
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
                        # Split content by any whitespace or comma, which handles most user formats.
                        keys_in_file = re.split(r'[\s,]+', content)
                        # Filter out any empty strings that may result from splitting and add to the set.
                        cleaned_keys = {key for key in keys_in_file if key}
                        all_keys.update(cleaned_keys)
                except Exception as e:
                    logger.error(f"Failed to read or parse key file '{filepath}': {e}")
    except Exception as e:
        logger.error(f"Failed to list files in directory '{path}': {e}")

    return all_keys


class KeySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing API keys.
    """

    def sync(self, config: Config, db_path: str):
        """
        Performs a full synchronization cycle for API keys.

        It iterates through all configured providers, reads their respective key files
        from disk, and calls the database synchronization function to align the DB state.
        """
        logger.info("Starting API key synchronization cycle...")

        for provider_name, provider_config in config.providers.items():
            if not provider_config.enabled:
                logger.debug(f"Provider '{provider_name}' is disabled in config. Skipping key sync.")
                continue

            # Check if keys_path is configured for this provider.
            if not provider_config.keys_path:
                logger.debug(f"No 'keys_path' configured for provider '{provider_name}'. Skipping key sync.")
                continue

            logger.info(f"Syncing keys for provider: '{provider_name}'")

            # Step 1: Read all unique keys from the specified directory.
            keys_from_file = _read_keys_from_directory(provider_config.keys_path)
            if not keys_from_file:
                logger.warning(f"No keys found in directory '{provider_config.keys_path}' for provider '{provider_name}'.")
                # We still proceed to sync, as this might be intentional (to remove all keys).

            # Step 2: Aggregate all models supported by this provider from the config.
            all_provider_models: List[str] = [
                model
                for model_list in provider_config.models.values()
                for model in model_list
            ]

            # Step 3: Call the database function to perform the actual synchronization.
            database.sync_keys_for_provider(
                db_path=db_path,
                provider_name=provider_name,
                keys_from_file=keys_from_file,
                provider_models=all_provider_models
            )

        logger.info("API key synchronization cycle finished.")

