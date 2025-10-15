# src/services/probes/__init__.py

import logging
from typing import Dict, Type, List

from src.config.schemas import Config
from src.core.probes import IResourceProbe
from src.db.database import DatabaseManager

# Import concrete probe implementations
from src.services.probes.key_probe import KeyProbe

logger = logging.getLogger(__name__)

_PROBE_CLASSES: Dict[str, Type[IResourceProbe]] = {
    "keys": KeyProbe,
}

def get_all_probes(config: Config, db_manager: DatabaseManager) -> List[IResourceProbe]:
    """
    Factory function to create instances of all registered probes (Async Version).

    This function iterates through the probe registry, instantiates each probe
    with the necessary configuration and the DatabaseManager instance, and returns
    them as a list.

    Args:
        config: The main application configuration object.
        db_manager: An instance of the DatabaseManager.

    Returns:
        A list of initialized probe instances.
    """
    all_probes: List[IResourceProbe] = []
    for probe_name, probe_class in _PROBE_CLASSES.items():
        try:
            instance = probe_class(config=config, db_manager=db_manager)
            all_probes.append(instance)
        except Exception as e:
            logger.error(f"Failed to initialize probe '{probe_name}': {e}", exc_info=True)
    
    return all_probes
