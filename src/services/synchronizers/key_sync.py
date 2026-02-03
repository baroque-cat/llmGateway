# src/services/synchronizers/key_sync.py

import logging
import os
import re

from src.core.accessor import ConfigAccessor

# REFACTORED: Import new TypedDict for state representation.
from src.core.interfaces import IResourceSyncer, ProviderKeyState
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def _read_keys_from_directory(path: str) -> set[str]:
    """
    Reads all files in a specified directory, extracts API keys, and returns them as a unique set.
    This function performs synchronous file I/O, which is acceptable for this periodic task.
    This helper function is now intended to be called by the background worker during the "Read Phase".
    """
    if not os.path.exists(path) or not os.path.isdir(path):
        logger.warning(
            f"Key directory not found or is not a directory: '{path}'. Skipping."
        )
        return set()

    all_keys: set[str] = set()
    try:
        for filename in os.listdir(path):
            filepath = os.path.join(path, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, encoding="utf-8") as f:
                        content = f.read()
                        keys_in_file = re.split(r"[\s,]+", content)
                        cleaned_keys = {key for key in keys_in_file if key}
                        all_keys.update(cleaned_keys)
                except Exception as e:
                    logger.error(
                        f"Failed to read or parse key file '{filepath}': {e}",
                        exc_info=True,
                    )
    except Exception as e:
        logger.error(f"Failed to list files in directory '{path}': {e}", exc_info=True)

    return all_keys


class KeySyncer(IResourceSyncer):
    """
    A concrete implementation of IResourceSyncer for synchronizing API keys.
    This class now implements the "apply_state" pattern, acting as an executor
    for a pre-calculated synchronization plan.
    """

    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the KeySyncer with its required dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        self.accessor = accessor
        self.db_manager = db_manager

    # REFACTORED: The old 'sync' method is replaced by 'apply_state'.
    # This method receives a complete snapshot of the desired state for all providers
    # and is responsible for applying this state to the database.
    async def apply_state(
        self,
        provider_id_map: dict[str, int],
        desired_state: dict[str, ProviderKeyState],
    ):
        """
        Performs a full synchronization for API keys by applying the desired state to the database.

        Args:
            provider_id_map: A mapping from provider name to its database ID.
            desired_key_state: A dictionary where keys are provider names and values
                               are ProviderKeyState objects.
        """
        logger.info("Applying desired key state to the database...")

        if not desired_state:
            logger.info("No key state to apply. Key synchronization cycle finished.")
            return

        for provider_name, state in desired_state.items():
            try:
                provider_id = provider_id_map.get(provider_name)
                if provider_id is None:
                    logger.error(
                        f"Provider '{provider_name}' not found in the ID map. Skipping key sync for this provider."
                    )
                    continue

                keys_from_file = state["keys_from_files"]
                models_from_config = state["models_from_config"]

                logger.info(
                    f"Applying state for provider '{provider_name}' (ID: {provider_id}): "
                    f"{len(keys_from_file)} keys and {len(models_from_config)} models."
                )

                # IMPORTANT: This call assumes that `db_manager.keys.sync` has been updated
                # to accept the 'models_from_config' argument and to handle the logic
                # for removing obsolete key-model relationships.
                await self.db_manager.keys.sync(
                    provider_name=provider_name,
                    provider_id=provider_id,
                    keys_from_file=keys_from_file,
                    provider_models=models_from_config,
                )
            except Exception as e:
                # Isolate failures to prevent one provider from halting the entire sync process.
                logger.error(
                    f"An unexpected error occurred while applying key state for provider '{provider_name}': {e}",
                    exc_info=True,
                )

        logger.info("Finished applying desired key state.")
