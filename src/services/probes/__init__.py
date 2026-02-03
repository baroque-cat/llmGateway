# src/services/probes/__init__.py

import logging
from typing import Dict, List, Type

# REFACTORED: Import ConfigAccessor instead of the raw Config schema.
# This makes the factory's dependencies explicit and aligned with the new architecture.
from src.core.accessor import ConfigAccessor
from src.core.http_client_factory import HttpClientFactory
from src.core.probes import IResourceProbe
from src.db.database import DatabaseManager

# Import concrete probe implementations
from src.services.probes.key_probe import KeyProbe

logger = logging.getLogger(__name__)

# A registry to map probe type names to their classes.
_PROBE_CLASSES: dict[str, type[IResourceProbe]] = {
    "keys": KeyProbe,
}


# REFACTORED: The function signature is updated to accept ConfigAccessor.
def get_all_probes(
    accessor: ConfigAccessor,
    db_manager: DatabaseManager,
    client_factory: HttpClientFactory,
) -> list[IResourceProbe]:
    """
    Factory function to create instances of all registered probes (Async Version).

    This function iterates through the probe registry, instantiates each probe
    with all necessary dependencies (accessor, db_manager, client_factory), and
    returns them as a list.

    Args:
        accessor: An instance of ConfigAccessor for safe config access.
        db_manager: An instance of the DatabaseManager.
        client_factory: A factory for creating and managing httpx.AsyncClient instances.

    Returns:
        A list of initialized probe instances.
    """
    all_probes: list[IResourceProbe] = []
    for probe_name, probe_class in _PROBE_CLASSES.items():
        try:
            # REFACTORED: Pass the accessor instead of the raw config object.
            # This aligns with the new IResourceProbe constructor contract defined
            # in src/core/probes.py.
            instance = probe_class(
                accessor=accessor, db_manager=db_manager, client_factory=client_factory
            )
            all_probes.append(instance)
            logger.debug(f"Successfully initialized probe: '{probe_name}'")
        except Exception as e:
            logger.error(
                f"Failed to initialize probe '{probe_name}': {e}", exc_info=True
            )

    return all_probes
