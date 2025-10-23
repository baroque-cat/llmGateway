# src/services/synchronizers/__init__.py

import logging
from typing import Dict, Type, List

from src.core.types import IResourceSyncer
# REFACTORED: Import the dependencies that are now required by the factory.
from src.core.accessor import ConfigAccessor
from src.db.database import DatabaseManager

# Import concrete syncer implementations
from src.services.synchronizers.key_sync import KeySyncer
from src.services.synchronizers.proxy_sync import ProxySyncer

logger = logging.getLogger(__name__)

# A registry to map syncer type names to their classes.
# This allows for easy extension with new resource types in the future.
_SYNCER_CLASSES: Dict[str, Type[IResourceSyncer]] = {
    "keys": KeySyncer,
    "proxies": ProxySyncer,
}

# REFACTORED: The function signature is updated to accept dependencies.
def get_all_syncers(accessor: ConfigAccessor, db_manager: DatabaseManager) -> List[IResourceSyncer]:
    """
    Factory function to create instances of all registered synchronizers.

    This function iterates through the synchronizer registry, instantiates each one
    with all necessary dependencies (accessor, db_manager), and returns them as a list.
    The background worker can then polymorphically call the `sync` method on each instance.

    Args:
        accessor: An instance of ConfigAccessor for safe config access.
        db_manager: An instance of the DatabaseManager for async DB access.

    Returns:
        A list of initialized synchronizer instances.
    """
    all_syncers: List[IResourceSyncer] = []
    for syncer_name, syncer_class in _SYNCER_CLASSES.items():
        try:
            # REFACTORED: Pass the required dependencies to the constructor.
            # This aligns with the new IResourceSyncer contract and the refactored
            # concrete syncer classes (KeySyncer, ProxySyncer).
            instance = syncer_class(accessor=accessor, db_manager=db_manager)
            all_syncers.append(instance)
            logger.debug(f"Successfully initialized synchronizer: '{syncer_name}'")
        except Exception as e:
            logger.error(f"Failed to initialize synchronizer '{syncer_name}': {e}", exc_info=True)
            
    return all_syncers
