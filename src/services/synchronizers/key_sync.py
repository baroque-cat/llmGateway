# src/services/synchronizers/key_sync.py

import json
import logging
import os
import re
from typing import Any

from src.core.accessor import ConfigAccessor

# REFACTORED: Import new TypedDict for state representation.
from src.core.interfaces import IResourceSyncer, ProviderKeyState
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


def read_keys_from_directory(path: str) -> set[str]:
    """
    Reads all API key files (.txt and .ndjson) from a directory and returns
    a deduplicated set of keys.

    Supported formats:
      - ``.txt``: plain text files; content is split on whitespace and commas.
      - ``.ndjson``: JSON Lines format; each line is a JSON object with a
        ``"value"`` field containing the key.

    Files with other extensions (``.gitkeep``, ``.DS_Store``, files without
    extension) are silently ignored. The original files are never modified.

    NDJSON parsing:
      - Empty lines are silently skipped.
      - Non‑JSON lines are logged as warnings and skipped.
      - JSON objects without a ``"value"`` field are logged and skipped.
      - ``"value": null`` is logged and skipped.
      - A non‑string ``"value"`` is coerced via ``str()`` with a warning.
      - Files are opened with ``encoding="utf-8-sig"`` to handle optional BOM.

    Args:
        path: Path to the directory containing key files.

    Returns:
        A ``set[str]`` of unique API keys, or an empty set if the directory
        does not exist or contains no valid key files.
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
            if not os.path.isfile(filepath):
                continue

            ext = os.path.splitext(filename)[1].lower()
            if ext not in (".txt", ".ndjson"):
                logger.debug(f"Skipping non-key file: '{filename}'")
                continue

            try:
                if ext == ".txt":
                    _read_txt_file(filepath, all_keys)
                elif ext == ".ndjson":
                    _read_ndjson_file(filepath, all_keys)
            except Exception as e:
                logger.error(
                    f"Failed to read or parse key file '{filepath}': {e}",
                    exc_info=True,
                )
    except Exception as e:
        logger.error(f"Failed to list files in directory '{path}': {e}", exc_info=True)

    return all_keys


def _read_txt_file(filepath: str, all_keys: set[str]) -> None:
    """Read a plain text key file and add keys to ``all_keys``."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    keys_in_file = re.split(r"[\s,]+", content)
    cleaned_keys = {key for key in keys_in_file if key}
    all_keys.update(cleaned_keys)


def _read_ndjson_file(filepath: str, all_keys: set[str]) -> None:
    """Read an NDJSON key file line‑by‑line and add keys to ``all_keys``."""
    with open(filepath, encoding="utf-8-sig") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue  # empty line → skip silently

            try:
                obj: Any = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning(
                    f"Skipping non-JSON line {line_num} in '{filepath}': {stripped!r}"
                )
                continue

            if not isinstance(obj, dict):
                logger.warning(
                    f"Skipping non-dict JSON line {line_num} in '{filepath}'"
                )
                continue

            if "value" not in obj:
                logger.warning(
                    f"Skipping JSON without 'value' field at line {line_num} "
                    f"in '{filepath}': {obj}"
                )
                continue

            raw_value: Any = obj["value"]  # pyright: ignore[reportUnknownVariableType]
            if raw_value is None:
                logger.warning(
                    f"Skipping null 'value' at line {line_num} in '{filepath}'"
                )
                continue

            if isinstance(raw_value, str):
                all_keys.add(raw_value)
            else:
                logger.warning(
                    f"Coercing non-string 'value' ({type(raw_value).__name__}) "  # pyright: ignore[reportUnknownArgumentType]
                    f"to str at line {line_num} in '{filepath}'"
                )
                all_keys.add(
                    str(raw_value)
                )  # pyright: ignore[reportUnknownArgumentType]


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
