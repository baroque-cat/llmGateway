# src/services/probes/__init__.py

import logging
from typing import Dict, Type, List

from src.config.schemas import Config
from src.core.probes import IResourceProbe

# Import concrete probe implementations
from src.services.probes.key_probe import KeyProbe
# Future probes like ProxyProbe would be imported here
# from src.services.probes.proxy_probe import ProxyProbe

logger = logging.getLogger(__name__)

# A registry to map probe type names to their classes.
# This makes adding new probes trivial: just add the class to this dictionary.
_PROBE_CLASSES: Dict[str, Type[IResourceProbe]] = {
    "keys": KeyProbe,
    # "proxies": ProxyProbe, # Example for when you add a proxy probe
}

def get_all_probes(config: Config, db_path: str) -> List[IResourceProbe]:
    """
    Factory function to create instances of all registered probes.

    This function iterates through the probe registry, instantiates each probe
    with the necessary configuration and database path, and returns them as a list.
    The background worker can then polymorphically run the `run_cycle` method on each.

    Args:
        config: The main application configuration object.
        db_path: The file path to the SQLite database.

    Returns:
        A list of initialized probe instances.
    """
    all_probes: List[IResourceProbe] = []
    for probe_name, probe_class in _PROBE_CLASSES.items():
        try:
            instance = probe_class(config=config, db_path=db_path)
            all_probes.append(instance)
        except Exception as e:
            # It's better to log this error than to crash the whole worker
            # if one probe fails to initialize.
            logger.error(f"Failed to initialize probe '{probe_name}': {e}", exc_info=True)
    
    return all_probes
