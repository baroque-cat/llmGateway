# src/services/synchronizers/__init__.py

from typing import Dict, Type, List

from src.core.types import IResourceSyncer

# Import concrete syncer implementations
from src.services.synchronizers.key_sync import KeySyncer
from src.services.synchronizers.proxy_sync import ProxySyncer

# A registry to map syncer type names to their classes.
# This allows for easy extension with new resource types in the future.
_SYNCER_CLASSES: Dict[str, Type[IResourceSyncer]] = {
    "keys": KeySyncer,
    "proxies": ProxySyncer,
}

def get_all_syncers() -> List[IResourceSyncer]:
    """
    Factory function to create instances of all registered synchronizers.

    This function iterates through the synchronizer registry, instantiates each one,
    and returns them as a list. The background worker can then polymorphically
    call the `sync` method on each instance.

    Returns:
        A list of initialized synchronizer instances.
    """
    all_syncers: List[IResourceSyncer] = []
    for syncer_name, syncer_class in _SYNCER_CLASSES.items():
        try:
            instance = syncer_class()
            all_syncers.append(instance)
        except Exception as e:
            print(f"ERROR: Failed to initialize synchronizer '{syncer_name}': {e}")
            
    return all_syncers
