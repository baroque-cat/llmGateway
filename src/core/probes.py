# src/core/probes.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import logging
import time
from collections import defaultdict

from src.config.schemas import Config
from src.core.models import CheckResult

logger = logging.getLogger(__name__)

class IResourceProbe(ABC):
    """
    Abstract Base Class (Interface) for all resource probes.

    This class defines a universal contract for any service that checks the
    health of a resource (like an API key or a proxy). It uses the Template
    Method design pattern, where the `run_cycle` method defines the skeleton
    of the checking algorithm, and subclasses must implement the specific steps.
    """

    def __init__(self, config: Config, db_path: str):
        """
        Initializes the probe with application configuration and DB path.

        Args:
            config: The main application configuration object.
            db_path: The file path to the SQLite database.
        """
        self.config = config
        self.db_path = db_path

    def run_cycle(self):
        """
        Executes one full checking cycle for all resources.
        This is the main entry point called by the background worker.
        """
        logger.info(f"Starting resource check cycle for {self.__class__.__name__}...")
        
        try:
            resources_to_check = self._get_resources_to_check()
            if not resources_to_check:
                logger.info("No resources are due for a check in this cycle.")
                return

            logger.info(f"Found {len(resources_to_check)} resource(s) to check.")

            # Group resources by provider_name to apply provider-specific batching policies.
            grouped_resources = defaultdict(list)
            for resource in resources_to_check:
                grouped_resources[resource.get('provider_name')].append(resource)

            for provider_name, resources in grouped_resources.items():
                provider_config = self.config.providers.get(provider_name)
                if not provider_config:
                    logger.warning(f"No configuration found for provider '{provider_name}'. Skipping {len(resources)} resources.")
                    continue
                
                # Get batching settings from the provider's health policy.
                policy = provider_config.health_policy
                batch_size = getattr(policy, 'batch_size', 20)  # Default batch size if not set
                batch_delay_sec = getattr(policy, 'batch_delay_sec', 5) # Default delay

                logger.info(f"Processing {len(resources)} resources for provider '{provider_name}' with batch_size={batch_size} and delay={batch_delay_sec}s.")

                for i in range(0, len(resources), batch_size):
                    batch = resources[i:i + batch_size]
                    logger.debug(f"Processing batch {i//batch_size + 1} for '{provider_name}' with {len(batch)} resources.")
                    
                    for resource in batch:
                        try:
                            result = self._check_resource(resource)
                            self._update_resource_status(resource, result)
                        except Exception:
                            # Isolate failures: if one resource check fails, log it and move on.
                            logger.error(f"An unexpected error occurred while checking resource: {resource}", exc_info=True)
                    
                    # If this is not the last batch, sleep before the next one.
                    if i + batch_size < len(resources):
                        logger.debug(f"Batch for '{provider_name}' finished. Waiting for {batch_delay_sec} seconds...")
                        time.sleep(batch_delay_sec)

        except Exception:
            logger.critical(f"A critical error occurred in the main run_cycle of {self.__class__.__name__}", exc_info=True)
        
        logger.info(f"Resource check cycle for {self.__class__.__name__} finished.")

    @abstractmethod
    def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches the list of resources that are due for a health check.
        Must be implemented by subclasses.

        Returns:
            A list of dictionaries, where each dictionary represents a resource to check.
        """
        raise NotImplementedError

    @abstractmethod
    def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Performs the actual health check on a single resource.
        Must be implemented by subclasses.

        Args:
            resource: A dictionary containing information about the resource to check.

        Returns:
            A CheckResult object with the outcome of the check.
        """
        raise NotImplementedError

    @abstractmethod
    def _update_resource_status(self, resource: Dict[str, Any], result: CheckResult):
        """
        Updates the status of the resource in the database based on the check result.
        Must be implemented by subclasses.

        Args:
            resource: The resource that was checked.
            result: The CheckResult from the check.
        """
        raise NotImplementedError

