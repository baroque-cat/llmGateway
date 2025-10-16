# src/core/probes.py

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from collections import defaultdict

import httpx

from src.config.schemas import Config
from src.core.models import CheckResult
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

# --- Constants ---
# Limits the number of providers that can be processed concurrently.
# This prevents overwhelming the system or external APIs with too many parallel tasks.
MAX_CONCURRENT_PROVIDERS = 10

class IResourceProbe(ABC):
    """
    Abstract Base Class (Interface) for all resource probes (Async Version).

    This class defines a universal contract for any service that checks the
    health of a resource. It uses the Template Method design pattern and relies
    on asyncio for concurrent processing of providers.
    """

    def __init__(self, config: Config, db_manager: DatabaseManager, http_client: httpx.AsyncClient):
        """
        Initializes the probe with application configuration, DatabaseManager, and HTTP client.

        Args:
            config: The main application configuration object.
            db_manager: An instance of the DatabaseManager for async DB access.
            http_client: A long-lived instance of httpx.AsyncClient.
        """
        self.config = config
        self.db_manager = db_manager
        self.http_client = http_client
        # A semaphore to limit the number of concurrently running provider batches.
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROVIDERS)

    async def run_cycle(self):
        """
        Executes one full checking cycle for all resources concurrently.
        This is the main entry point called by the background worker.
        """
        logger.info(f"Starting async resource check cycle for {self.__class__.__name__}...")
        
        try:
            resources_to_check = await self._get_resources_to_check()
            if not resources_to_check:
                logger.info("No resources are due for a check in this cycle.")
                return

            logger.info(f"Found {len(resources_to_check)} resource(s) to check.")

            grouped_resources = defaultdict(list)
            for resource in resources_to_check:
                grouped_resources[resource.get('provider_name')].append(resource)

            tasks = [
                self._process_provider_batch(provider_name, resources)
                for provider_name, resources in grouped_resources.items()
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result, task in zip(results, tasks):
                if isinstance(result, Exception):
                    # This is a bit of a workaround to get context back from the task.
                    provider_name = task.get_name()
                    logger.error(f"An error occurred while processing the batch for provider '{provider_name}'.", exc_info=result)

        except Exception:
            logger.critical(f"A critical error occurred in the main run_cycle of {self.__class__.__name__}", exc_info=True)
        
        logger.info(f"Async resource check cycle for {self.__class__.__name__} finished.")


    async def _process_provider_batch(self, provider_name: str, resources: List[Dict[str, Any]]):
        """
        Processes all resources for a single provider, respecting its batching policy.
        This coroutine is executed concurrently for different providers.
        """
        # Set the task name for better logging in case of an exception in gather
        asyncio.current_task().set_name(provider_name)

        async with self.semaphore:
            provider_config = self.config.providers.get(provider_name)
            if not provider_config:
                logger.warning(f"No configuration found for provider '{provider_name}'. Skipping {len(resources)} resources.")
                return
            
            policy = provider_config.health_policy
            batch_size = policy.batch_size
            batch_delay_sec = policy.batch_delay_sec

            logger.info(f"Processing {len(resources)} resources for '{provider_name}' with batch_size={batch_size} and delay={batch_delay_sec}s.")

            for i in range(0, len(resources), batch_size):
                batch = resources[i:i + batch_size]
                logger.debug(f"Processing batch {i//batch_size + 1} for '{provider_name}' with {len(batch)} resources.")
                
                # Concurrently check all resources within the current batch
                check_tasks = [self._check_and_update_resource(res) for res in batch]
                await asyncio.gather(*check_tasks, return_exceptions=True)
                
                if i + batch_size < len(resources):
                    logger.debug(f"Batch for '{provider_name}' finished. Waiting for {batch_delay_sec} seconds...")
                    await asyncio.sleep(batch_delay_sec)
            
            logger.info(f"Successfully finished processing batch for provider '{provider_name}'.")

    async def _check_and_update_resource(self, resource: Dict[str, Any]):
        """
        Helper coroutine to wrap the check and update logic for a single resource.
        This allows us to run multiple of these concurrently within a batch.
        """
        try:
            result = await self._check_resource(resource)
            await self._update_resource_status(resource, result)
        except Exception:
            logger.error(f"An unexpected error occurred while checking and updating resource: {resource}", exc_info=True)

    @abstractmethod
    async def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches the list of resources due for a health check. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Performs the health check on a single resource. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def _update_resource_status(self, resource: Dict[str, Any], result: CheckResult):
        """
        Updates the resource's status in the database. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError
