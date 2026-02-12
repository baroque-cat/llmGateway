# src/services/synchronizers/key_sync.py

import logging
import os
import re
import tempfile

from src.core.accessor import ConfigAccessor

# REFACTORED: Import new TypedDict for state representation.
from src.core.interfaces import IResourceSyncer, ProviderKeyState
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def _sanitize_key_file(filepath: str) -> None:
    """
    Atomically rewrites a key file to remove duplicate lines.
    Uses a temporary file and os.replace for atomicity to prevent data loss on crash.
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()

        # Track seen keys and preserve order of first occurrence
        seen_keys: set[str] = set()
        unique_lines: list[str] = []
        for line in lines:
            # Split line into potential multiple keys (like the reader does)
            potential_keys = re.split(r"[\s,]+", line.strip())
            for key in potential_keys:
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    unique_lines.append(key + "\n")

        # Rewrite if:
        # 1. There are duplicate keys, OR
        # 2. Any line contained multiple keys (needs normalization to one key per line)
        original_key_count = 0
        for line in lines:
            stripped_line = line.strip()
            if stripped_line:
                # Count how many keys were on this line originally
                keys_on_line = [k for k in re.split(r"[\s,]+", stripped_line) if k]
                original_key_count += len(keys_on_line)

        needs_rewrite = len(
            unique_lines
        ) < original_key_count or any(  # Duplicates found
            len(re.split(r"[\s,]+", line.strip())) > 1 for line in lines if line.strip()
        )  # Multi-key lines exist

        if needs_rewrite:
            with tempfile.NamedTemporaryFile(
                "w", dir=os.path.dirname(filepath), delete=False, encoding="utf-8"
            ) as tf:
                tf.writelines(unique_lines)
                temp_name = tf.name

            # Atomic replace
            os.replace(temp_name, filepath)
            logger.info(f"Sanitized key file '{filepath}', removed duplicates.")

    except PermissionError:
        # Common in containerized environments with read-only mounts
        logger.warning(
            f"Permission denied while sanitizing '{filepath}'. Skipping cleanup."
        )
    except Exception as e:
        logger.error(f"Failed to sanitize key file '{filepath}': {e}", exc_info=True)


def read_keys_from_directory(path: str) -> set[str]:
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
                # Sanitize the file first to remove any duplicates
                _sanitize_key_file(filepath)

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

    def get_resource_type(self) -> str:
        """Returns the resource type identifier for this syncer."""
        return "keys"

    # REFACTORED: The old 'sync' method is replaced by 'apply_state'.
    # This method receives a complete snapshot of the desired state for all providers
    # and is responsible for applying this state to the database.
    async def apply_state(
        self,
        provider_id_map: dict[str, int],
        desired_state: dict[str, ProviderKeyState],
    ) -> None:
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
