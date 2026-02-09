# src/core/probes.py

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List

# REFACTORED: Import ConfigAccessor instead of Config.
from src.core.accessor import ConfigAccessor
from src.core.http_client_factory import HttpClientFactory
from src.core.models import CheckResult
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

# REFACTORED: The hardcoded constant is removed.
# The concurrency limit will now be read from the config.


class IResourceProbe(ABC):
    """
    Abstract Base Class (Interface) for all resource probes (Async Version).

    This class defines a universal contract for any service that checks the
    health of a resource. It uses the Template Method design pattern and relies
    on asyncio for concurrent processing of providers.
    """

    # REFACTORED: The constructor now accepts ConfigAccessor.
    def __init__(
        self,
        accessor: ConfigAccessor,
        db_manager: DatabaseManager,
        client_factory: HttpClientFactory,
    ):
        """
        Initializes the probe with dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
            client_factory: A factory for creating and managing httpx.AsyncClient instances.
        """
        self.accessor = accessor
        self.db_manager = db_manager
        self.client_factory = client_factory

        # REFACTORED: The semaphore limit is now dynamically read from the worker config.
        # This makes the probe's behavior configurable.
        concurrency_limit = self.accessor.get_worker_concurrency()
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def run_cycle(self) -> None:
        """
        Executes one full checking cycle for all resources concurrently.
        This is the main entry point called by the background worker.
        """
        logger.info(
            f"Starting async resource check cycle for {self.__class__.__name__}..."
        )

        try:
            resources_to_check = await self._get_resources_to_check()
            if not resources_to_check:
                logger.info("No resources are due for a check in this cycle.")
                return

            logger.info(f"Found {len(resources_to_check)} resource(s) to check.")

            grouped_resources: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for resource in resources_to_check:
                p_name = resource.get("provider_name")
                if isinstance(p_name, str):
                    grouped_resources[p_name].append(resource)

            tasks = [
                asyncio.create_task(
                    self._process_provider_batch(provider_name, resources)
                )
                for provider_name, resources in grouped_resources.items()
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result, task in zip(results, tasks):
                if isinstance(result, Exception):
                    # This is a bit of a workaround to get context back from the task.
                    provider_name = task.get_name()
                    logger.error(
                        f"An error occurred while processing the batch for provider '{provider_name}'.",
                        exc_info=result,
                    )

        except Exception:
            logger.critical(
                f"A critical error occurred in the main run_cycle of {self.__class__.__name__}",
                exc_info=True,
            )

        logger.info(
            f"Async resource check cycle for {self.__class__.__name__} finished."
        )

    async def _process_provider_batch(
        self, provider_name: str, resources: list[dict[str, Any]]
    ) -> None:
        """
        Processes all resources for a single provider, respecting its batching policy.
        This coroutine is executed concurrently for different providers.
        """
        # Set the task name for better logging in case of an exception in gather
        current_task = asyncio.current_task()
        if current_task:
            current_task.set_name(provider_name)

        async with self.semaphore:
            # REFACTORED: Use the accessor to get the provider policy directly.
            # This ensures we are using the facade pattern correctly and not accessing
            # internal implementation details like 'worker_health_policy'.
            policy = self.accessor.get_health_policy(provider_name)

            if not policy:
                logger.warning(
                    f"No configuration/policy found for provider '{provider_name}'. Skipping {len(resources)} resources."
                )
                return

            batch_size = policy.batch_size
            batch_delay_sec = policy.batch_delay_sec

            logger.info(
                f"Processing {len(resources)} resources for '{provider_name}' with batch_size={batch_size} and delay={batch_delay_sec}s."
            )

            for i in range(0, len(resources), batch_size):
                batch = resources[i : i + batch_size]
                logger.debug(
                    f"Processing batch {i // batch_size + 1} for '{provider_name}' with {len(batch)} resources."
                )

                # Concurrently check all resources within the current batch
                check_tasks = [self._check_and_update_resource(res) for res in batch]
                await asyncio.gather(*check_tasks, return_exceptions=True)

                if i + batch_size < len(resources):
                    logger.debug(
                        f"Batch for '{provider_name}' finished. Waiting for {batch_delay_sec} seconds..."
                    )
                    await asyncio.sleep(batch_delay_sec)

            logger.info(
                f"Successfully finished processing batch for provider '{provider_name}'."
            )

    async def _check_and_update_resource(self, resource: dict[str, Any]) -> None:
        """
        Helper coroutine to wrap the check and update logic for a single resource.
        This allows us to run multiple of these concurrently within a batch.
        """
        try:
            result = await self._check_resource(resource)
            await self._update_resource_status(resource, result)
        except Exception:
            logger.error(
                f"An unexpected error occurred while checking and updating resource: {resource}",
                exc_info=True,
            )

    @abstractmethod
    async def _get_resources_to_check(self) -> list[Any]:
        """
        Fetches the list of resources due for a health check. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def _check_resource(self, resource: dict[str, Any]) -> CheckResult:
        """
        Performs the health check on a single resource. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def _update_resource_status(
        self, resource: dict[str, Any], result: CheckResult
    ) -> None:
        """
        Updates the resource's status in the database. (Async)
        Must be implemented by subclasses.
        """
        raise NotImplementedError
