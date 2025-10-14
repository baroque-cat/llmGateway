# src/core/probes.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config.schemas import Config
from src.core.models import CheckResult

logger = logging.getLogger(__name__)

# --- Constants ---
# Maximum number of parallel threads to use for checking different providers.
# This prevents overwhelming the system with too many concurrent checks.
MAX_PROBE_WORKERS = 10

class IResourceProbe(ABC):
    """
    Abstract Base Class (Interface) for all resource probes.

    This class defines a universal contract for any service that checks the
    health of a resource (like an API key or a proxy). It uses the Template
    Method design pattern, where the `run_cycle` method defines the skeleton
    of the checking algorithm, and subclasses must implement the specific steps.

    The run_cycle is now implemented to process different providers in parallel.
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
        Executes one full checking cycle for all resources in parallel.
        This is the main entry point called by the background worker.
        It fetches all resources due for a check, groups them by provider,
        and then processes each provider's group in a separate thread.
        """
        logger.info(f"Starting resource check cycle for {self.__class__.__name__}...")
        
        try:
            resources_to_check = self._get_resources_to_check()
            if not resources_to_check:
                logger.info("No resources are due for a check in this cycle.")
                return

            logger.info(f"Found {len(resources_to_check)} resource(s) to check.")

            # Group resources by provider_name to process them in parallel.
            grouped_resources = defaultdict(list)
            for resource in resources_to_check:
                grouped_resources[resource.get('provider_name')].append(resource)

            # Use a ThreadPoolExecutor to run checks for each provider concurrently.
            with ThreadPoolExecutor(max_workers=MAX_PROBE_WORKERS) as executor:
                # Submit a task to process each provider's resource batch.
                future_to_provider = {
                    executor.submit(self._process_provider_batch, provider_name, resources): provider_name
                    for provider_name, resources in grouped_resources.items()
                }
                
                # Process results as they are completed to log any errors.
                for future in as_completed(future_to_provider):
                    provider_name = future_to_provider[future]
                    try:
                        future.result()  # We call result() to raise any exceptions from the thread.
                        logger.info(f"Successfully finished processing batch for provider '{provider_name}'.")
                    except Exception:
                        logger.error(f"An error occurred while processing the batch for provider '{provider_name}'.", exc_info=True)

        except Exception:
            logger.critical(f"A critical error occurred in the main run_cycle of {self.__class__.__name__}", exc_info=True)
        
        logger.info(f"Resource check cycle for {self.__class__.__name__} finished.")


    def _process_provider_batch(self, provider_name: str, resources: List[Dict[str, Any]]):
        """
        Processes all resources for a single provider, respecting its specific batching policy.
        This method is designed to be executed in a separate thread.
        """
        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            logger.warning(f"No configuration found for provider '{provider_name}'. Skipping {len(resources)} resources.")
            return
        
        # Get batching settings from the provider's health policy.
        policy = provider_config.health_policy
        batch_size = getattr(policy, 'batch_size', 20)
        batch_delay_sec = getattr(policy, 'batch_delay_sec', 5)

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
            
            # If this is not the last batch for this provider, sleep before the next one.
            if i + batch_size < len(resources):
                logger.debug(f"Batch for '{provider_name}' finished. Waiting for {batch_delay_sec} seconds...")
                time.sleep(batch_delay_sec)


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
