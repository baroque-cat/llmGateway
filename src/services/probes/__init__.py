# src/services/probes/__init__.py

import logging
from typing import Dict, Type, List

# --- REFACTORED: httpx is no longer a direct dependency here ---
from src.config.schemas import Config
from src.core.probes import IResourceProbe
from src.db.database import DatabaseManager
# --- ADDED: Import the new factory dependency ---
from src.core.http_client_factory import HttpClientFactory

# Import concrete probe implementations
from src.services.probes.key_probe import KeyProbe

logger = logging.getLogger(__name__)

_PROBE_CLASSES: Dict[str, Type[IResourceProbe]] = {
    "keys": KeyProbe,
}

# --- REFACTORED: The function signature is updated to accept the factory ---
def get_all_probes(config: Config, db_manager: DatabaseManager, client_factory: HttpClientFactory) -> List[IResourceProbe]:
    """
    Factory function to create instances of all registered probes (Async Version).

    This function iterates through the probe registry, instantiates each probe
    with all necessary dependencies (config, db_manager, client_factory), and
    returns them as a list.

    Args:
        config: The main application configuration object.
        db_manager: An instance of the DatabaseManager.
        client_factory: A factory for creating and managing httpx.AsyncClient instances.

    Returns:
        A list of initialized probe instances.
    """
    all_probes: List[IResourceProbe] = []
    for probe_name, probe_class in _PROBE_CLASSES.items():
        try:
            # --- REFACTORED: Pass the client_factory instead of the http_client ---
            # The probe's constructor now expects the factory, adhering to the new
            # IResourceProbe contract we defined in src/core/probes.py.
            instance = probe_class(
                config=config,
                db_manager=db_manager,
                client_factory=client_factory
            )
            all_probes.append(instance)
        except Exception as e:
            logger.error(f"Failed to initialize probe '{probe_name}': {e}", exc_info=True)
    
    return all_probes

