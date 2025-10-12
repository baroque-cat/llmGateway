# src/services/key_manager.py

import os
import re
import logging
from typing import Set, List

from src.config.schemas import Config, ProviderConfig
from src.db import database

# Initialize a logger for this module. This is the standard Python practice.
# The logger's output (e.g., to console or a file) will be configured
# by the main application entry point, allowing for flexible logging levels.
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


def run_key_sync_cycle(config: Config, db_path: str):
    """
    Performs a full synchronization cycle for API keys.

    It iterates through all configured providers, reads their respective key files
    from disk, and calls the database synchronization function to align the DB state.

    This function is intended to be called periodically by a background worker.

    Args:
        config: The application's loaded configuration object.
        db_path: The file path to the SQLite database.
    """
    logger.info("Starting API key synchronization cycle...")

    # First, ensure the providers table itself is in sync with the config.
    provider_names_from_config = list(config.providers.keys())
    database.sync_providers(db_path, provider_names_from_config)

    for provider_name, provider_config in config.providers.items():
        if not provider_config.enabled:
            logger.debug(f"Provider '{provider_name}' is disabled in config. Skipping sync.")
            continue

        logger.info(f"Syncing keys for provider: '{provider_name}'")

        # Step 1: Read all unique keys from the specified directory.
        keys_from_file = _read_keys_from_directory(provider_config.keys_path)
        if not keys_from_file:
            logger.warning(f"No keys found in directory '{provider_config.keys_path}' for provider '{provider_name}'.")
            # We still proceed to sync, as this might be intentional (to remove all keys).

        # Step 2: Aggregate all models supported by this provider from the config.
        # The config can group models (e.g., 'llm', 'embedding'), so we flatten the lists.
        all_provider_models: List[str] = [
            model
            for model_list in provider_config.models.values()
            for model in model_list
        ]

        # Step 3: Call the database function to perform the actual synchronization.
        # This function will handle adding new keys, removing old ones, and managing
        # the key_model_status table entries.
        database.sync_keys_for_provider(
            db_path=db_path,
            provider_name=provider_name,
            keys_from_file=keys_from_file,
            provider_models=all_provider_models
        )

    logger.info("API key synchronization cycle finished.")

