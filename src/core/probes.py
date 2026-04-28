# src/core/probes.py

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from src.core.accessor import ConfigAccessor
from src.core.batching import AdaptiveBatchController
from src.core.constants import ErrorReason
from src.core.http_client_factory import HttpClientFactory
from src.core.models import CheckResult
from src.db.database import DatabaseManager

BatchCallback = Callable[[str, int, float, int, int, int], None]
"""Callback signature for batch-completion notifications.

Args:
    provider_name: The provider identifier (e.g. "openai", "anthropic").
    batch_size: Current batch size after the completed batch.
    batch_delay: Current batch delay in seconds.
    rate_limit_events: Cumulative rate-limit event counter.
    backoff_events: Cumulative moderate-backoff event counter.
    recovery_events: Cumulative recovery (ramp-up) event counter.
"""

logger = logging.getLogger(__name__)

# REFACTORED: The hardcoded constant is removed.
# The concurrency limit will now be read from the config.

# Timeout for a single provider task to prevent indefinite hanging.
# This value is a fallback; the actual timeout is read from the provider's health policy.
DEFAULT_TASK_TIMEOUT_SEC = 900


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
        on_batch_complete: BatchCallback | None = None,
    ):
        """
        Initializes the probe with dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
            client_factory: A factory for creating and managing httpx.AsyncClient instances.
            on_batch_complete: Optional callback invoked after each batch with the controller's
                updated state. Matches the ``BatchCallback`` signature.
        """
        self.accessor = accessor
        self.db_manager = db_manager
        self.client_factory = client_factory
        self._on_batch_complete: BatchCallback | None = on_batch_complete

        # REFACTORED: The semaphore limit is now dynamically read from the worker config.
        # This makes the probe's behavior configurable.
        concurrency_limit = self.accessor.get_worker_concurrency()
        self.semaphore = asyncio.Semaphore(concurrency_limit)

        # State management for active tasks to enable non-blocking dispatching.
        self.active_tasks: dict[str, asyncio.Task[None]] = {}

        # Adaptive batch controllers — one per provider, created lazily.
        self._batch_controllers: dict[str, AdaptiveBatchController] = {}

    async def run_cycle(self) -> None:
        """
        Executes one full checking cycle for all resources concurrently.
        This is the main entry point called by the background worker.
        The dispatcher logic has been refactored to be non-blocking.
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

            grouped_resources: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for resource in resources_to_check:
                p_name = resource.get("provider_name")
                if isinstance(p_name, str):
                    grouped_resources[p_name].append(resource)

            # Dispatch tasks for providers that are not already active.
            for provider_name, resources in grouped_resources.items():
                if provider_name in self.active_tasks:
                    # The provider is already being processed. Skip it to avoid overlap.
                    logger.debug(
                        f"Provider '{provider_name}' is already active. Skipping dispatch."
                    )
                    continue

                # Create a new task for this provider and track it.
                task = asyncio.create_task(
                    self._run_task_wrapper(provider_name, resources)
                )
                self.active_tasks[provider_name] = task

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
        Processes all resources for a single provider using an adaptive batch
        controller that dynamically adjusts ``batch_size`` and ``batch_delay``
        based on the per-batch classification of check results.

        The controller is created lazily (on first call) and reused across
        cycles so that state (e.g., consecutive successes) persists.

        On each completed batch the method:

        * Filters valid ``CheckResult`` objects from ``asyncio.gather``.
        * Feeds them to the controller's ``report_batch_result``.
        * Re-reads the controller's updated ``batch_size`` / ``batch_delay``.
        * Advances the iteration cursor by the actual batch size used.
        """
        # Set the task name for better logging in case of an exception in gather
        current_task = asyncio.current_task()
        if current_task:
            current_task.set_name(provider_name)

        async with self.semaphore:
            # REFACTORED: Use the accessor to get the provider policy directly.
            policy = self.accessor.get_health_policy(provider_name)

            if not policy:
                logger.warning(
                    f"No configuration/policy found for provider '{provider_name}'. "
                    f"Skipping {len(resources)} resources."
                )
                return

            # --- Adaptive batch controller (lazy init) ---
            controller = self._batch_controllers.get(provider_name)
            if controller is None:
                controller = AdaptiveBatchController(
                    config=policy.adaptive_batching,
                )
                self._batch_controllers[provider_name] = controller
                logger.info(
                    "[AdaptiveBatch] Provider '%s': controller created. "
                    "start_batch_size=%d, start_batch_delay=%.1fs, "
                    "bounds=[%d..%d keys, %.1f..%.1fs]",
                    provider_name,
                    controller.batch_size,
                    controller.batch_delay,
                    policy.adaptive_batching.min_batch_size,
                    policy.adaptive_batching.max_batch_size,
                    policy.adaptive_batching.min_batch_delay_sec,
                    policy.adaptive_batching.max_batch_delay_sec,
                )

            batch_size = controller.batch_size
            batch_delay = controller.batch_delay

            logger.info(
                "Processing %d resources for '%s' with initial batch_size=%d "
                "and delay=%.1fs.",
                len(resources),
                provider_name,
                batch_size,
                batch_delay,
            )

            i = 0
            batch_num = 0
            while i < len(resources):
                batch = resources[i : i + batch_size]
                batch_num += 1
                logger.debug(
                    "Batch %d for '%s': %d resources (i=%d, batch_size=%d).",
                    batch_num,
                    provider_name,
                    len(batch),
                    i,
                    batch_size,
                )

                # Concurrently check all resources within the current batch
                check_tasks = [self._check_and_update_resource(res) for res in batch]
                gather_results = await asyncio.gather(
                    *check_tasks, return_exceptions=True
                )

                # Filter out exceptions and None values, keeping only CheckResult
                valid_results: list[CheckResult] = [
                    r for r in gather_results if isinstance(r, CheckResult)
                ]

                # Report results to the adaptive controller
                controller.report_batch_result(valid_results)

                # Re-read dynamic values — they may have changed
                batch_size = controller.batch_size
                batch_delay = controller.batch_delay

                # Notify callback (if registered) with updated controller state
                if self._on_batch_complete:
                    self._on_batch_complete(
                        provider_name,
                        controller.batch_size,
                        controller.batch_delay,
                        controller.rate_limit_events,
                        controller.backoff_events,
                        controller.recovery_events,
                    )

                # Structured log after each batch
                fatal = sum(1 for r in valid_results if r.error_reason.is_fatal())
                rate_limited = sum(
                    1
                    for r in valid_results
                    if r.error_reason == ErrorReason.RATE_LIMITED
                )
                transient = sum(
                    1
                    for r in valid_results
                    if r.error_reason.is_retryable()
                    and not r.error_reason.is_fatal()
                    and r.error_reason != ErrorReason.RATE_LIMITED
                )
                logger.debug(
                    "[AdaptiveBatch] Provider '%s' batch %d: "
                    "total=%d, fatal=%d, rate_limited=%d, transient=%d, "
                    "next_batch_size=%d, next_delay=%.1fs, "
                    "consecutive_successes=%d",
                    provider_name,
                    batch_num,
                    len(valid_results),
                    fatal,
                    rate_limited,
                    transient,
                    controller.batch_size,
                    controller.batch_delay,
                    controller.consecutive_successes,
                )

                i += len(batch)

                if i < len(resources):
                    await asyncio.sleep(batch_delay)

            logger.info(
                "Successfully finished processing batch for provider '%s'.",
                provider_name,
            )

    async def _check_and_update_resource(
        self, resource: dict[str, Any]
    ) -> CheckResult | None:
        """
        Helper coroutine to wrap the check and update logic for a single resource.
        This allows us to run multiple of these concurrently within a batch.

        Returns:
            The ``CheckResult`` if the check completed successfully, or ``None``
            if an unexpected exception was caught (so the caller can filter).
        """
        try:
            result = await self._check_resource(resource)
            await self._update_resource_status(resource, result)
            return result
        except Exception:
            logger.error(
                f"An unexpected error occurred while checking and updating resource: {resource}",
                exc_info=True,
            )
            return None

    async def _run_task_wrapper(
        self, provider_name: str, resources: list[dict[str, Any]]
    ) -> None:
        """
        A safety wrapper for the provider batch processing task.
        It enforces a timeout and ensures the active_tasks registry is cleaned up.
        """
        policy = self.accessor.get_health_policy(provider_name)
        timeout_sec = policy.task_timeout_sec if policy else DEFAULT_TASK_TIMEOUT_SEC

        try:
            # Enforce a timeout to prevent indefinite hanging.
            await asyncio.wait_for(
                self._process_provider_batch(provider_name, resources),
                timeout=timeout_sec,
            )
        except TimeoutError:
            logger.error(
                f"Provider '{provider_name}' task timed out after {timeout_sec} seconds. Task was cancelled."
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred in the task for provider '{provider_name}': {e}",
                exc_info=True,
            )
        finally:
            # Critical: Always clean up the registry, even if the task failed or was cancelled.
            self.active_tasks.pop(provider_name, None)

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
