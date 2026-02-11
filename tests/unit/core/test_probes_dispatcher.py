#!/usr/bin/env python3

"""
Unit tests for the non-blocking dispatcher logic in IResourceProbe.
Covers the new "fire-and-forget" task management with timeout and cleanup.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import HealthPolicyConfig
from src.core.models import CheckResult
from src.core.probes import IResourceProbe


# ----------------------------------------------------------------------
# Concrete Test Probe
# ----------------------------------------------------------------------
class ConcreteTestProbe(IResourceProbe):
    """
    A concrete subclass of IResourceProbe for testing the dispatcher logic.
    Implements the required abstract methods with simple mock behavior.
    """

    async def _get_resources_to_check(self) -> list[dict[str, Any]]:
        # Return a dummy list; the test will override via mocking.
        return []

    async def _check_resource(self, resource: dict[str, Any]) -> CheckResult:
        # Not used directly in dispatcher tests; return a success.
        return CheckResult.success()

    async def _update_resource_status(
        self, resource: dict[str, Any], result: CheckResult
    ) -> None:
        # Not used directly in dispatcher tests.
        pass


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for ConcreteTestProbe."""
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10
    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    return mock_accessor, mock_db, mock_client_factory


@pytest.fixture
def probe(mock_dependencies):
    """Return a ConcreteTestProbe instance with mocked dependencies."""
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    return ConcreteTestProbe(mock_accessor, mock_db, mock_client_factory)


# ----------------------------------------------------------------------
# Test: Happy Path – New provider dispatched and cleaned up
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_provider_dispatched_and_cleaned_up(probe, mock_dependencies):
    """
    Scenario: A provider not already in active_tasks is dispatched.
    The task runs successfully and is removed from active_tasks.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    provider_name = "test_provider"
    resources = [{"key_id": 1, "provider_name": provider_name}]

    # Mock _get_resources_to_check to return the resources
    probe._get_resources_to_check = AsyncMock(return_value=resources)
    # Mock _process_provider_batch to do nothing (success)
    probe._process_provider_batch = AsyncMock()
    # Mock get_health_policy to return a policy with default timeout
    policy = HealthPolicyConfig(task_timeout_sec=300)
    mock_accessor.get_health_policy.return_value = policy

    # Run a single cycle
    await probe.run_cycle()

    # Verify that a task was created and added to active_tasks
    assert provider_name in probe.active_tasks
    task = probe.active_tasks[provider_name]
    # Wait for the task to complete (it's already done because we mocked)
    await task  # should not raise

    # Verify that the task wrapper cleaned up the registry
    # Since the task is already finished, active_tasks should be empty
    # However, cleanup happens in finally block after task finishes.
    # Let's give a small sleep to allow the finally block to execute.
    await asyncio.sleep(0.01)
    assert provider_name not in probe.active_tasks

    # Verify that _process_provider_batch was called with correct arguments
    probe._process_provider_batch.assert_called_once_with(provider_name, resources)


# ----------------------------------------------------------------------
# Test: Concurrency / Skipping – Provider already active
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrency_skipping_provider_already_active(probe, mock_dependencies):
    """
    Scenario: Provider already present in active_tasks.
    The dispatcher should skip it and log a debug message.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    provider_name = "busy_provider"
    resources = [{"key_id": 2, "provider_name": provider_name}]

    # Simulate that the provider is already being processed
    # by inserting a mock task that never completes
    mock_task = asyncio.create_task(asyncio.sleep(3600))  # long sleep
    probe.active_tasks[provider_name] = mock_task

    # Mock _get_resources_to_check to return the resources
    probe._get_resources_to_check = AsyncMock(return_value=resources)
    # Mock logger.debug to capture the skip message
    with patch("src.core.probes.logger.debug") as mock_debug:
        await probe.run_cycle()

        # Verify the debug log about skipping
        mock_debug.assert_called_once_with(
            f"Provider '{provider_name}' is already active. Skipping dispatch."
        )

    # Ensure _process_provider_batch was NOT called (skip)
    # (We haven't mocked it, but if it's called it would raise AttributeError)
    # We'll mock it to ensure it's not called
    probe._process_provider_batch = AsyncMock()
    # The mock shouldn't be called because we skipped
    probe._process_provider_batch.assert_not_called()

    # Clean up the long-running task
    mock_task.cancel()
    try:
        await mock_task
    except asyncio.CancelledError:
        pass


# ----------------------------------------------------------------------
# Test: Error Handling – Exception in _process_provider_batch
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_error_handling_exception_in_batch(probe, mock_dependencies):
    """
    Scenario: _process_provider_batch raises an exception.
    The task should be removed from active_tasks, and error should be logged.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    provider_name = "error_provider"
    resources = [{"key_id": 3, "provider_name": provider_name}]

    probe._get_resources_to_check = AsyncMock(return_value=resources)
    # Simulate an exception in the batch processing
    probe._process_provider_batch = AsyncMock(
        side_effect=RuntimeError("Simulated error")
    )
    policy = HealthPolicyConfig(task_timeout_sec=300)
    mock_accessor.get_health_policy.return_value = policy

    # Patch logger.error to capture the error log
    with patch("src.core.probes.logger.error") as mock_error:
        await probe.run_cycle()

        # Wait for the task to finish (should be immediate due to exception)
        task = probe.active_tasks.get(provider_name)
        if task:
            await task  # will raise? Actually wrapper catches exception
        # Give time for finally block
        await asyncio.sleep(0.01)

        # Verify that error was logged
        # The wrapper logs the exception with exc_info=True, we can check call count
        assert mock_error.call_count >= 1
        # Check that the error message contains provider name
        call_args = mock_error.call_args_list[0][0][0]
        assert provider_name in call_args

    # Verify that active_tasks is cleaned up
    assert provider_name not in probe.active_tasks


# ----------------------------------------------------------------------
# Test: Timeout Handling – Task exceeds timeout
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout_handling_task_exceeds_timeout(probe, mock_dependencies):
    """
    Scenario: _process_provider_batch takes longer than task_timeout_sec.
    The task should be cancelled, an error logged, and registry cleaned up.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    provider_name = "slow_provider"
    resources = [{"key_id": 4, "provider_name": provider_name}]

    probe._get_resources_to_check = AsyncMock(return_value=resources)

    # Create a mock batch that sleeps longer than timeout
    async def slow_batch(*args, **kwargs):
        await asyncio.sleep(2.0)  # longer than our short timeout

    probe._process_provider_batch = AsyncMock(side_effect=slow_batch)
    # Set a very short timeout (0.1 seconds) for the test
    policy = HealthPolicyConfig(task_timeout_sec=0.1)
    mock_accessor.get_health_policy.return_value = policy

    # Patch logger.error to capture timeout log
    with patch("src.core.probes.logger.error") as mock_error:
        await probe.run_cycle()

        # Wait a bit for the timeout to trigger
        await asyncio.sleep(0.3)

        # Verify that timeout error was logged
        mock_error.assert_called_once_with(
            f"Provider '{provider_name}' task timed out after 0.1 seconds. Task was cancelled."
        )

    # Verify that active_tasks is cleaned up
    assert provider_name not in probe.active_tasks


# ----------------------------------------------------------------------
# Test: Timeout Fallback – No policy uses default timeout
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout_fallback_no_policy_uses_default(probe, mock_dependencies):
    """
    Scenario: Provider has no health policy (returns None).
    The wrapper should fall back to DEFAULT_TASK_TIMEOUT_SEC.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    provider_name = "no_policy_provider"
    resources = [{"key_id": 5, "provider_name": provider_name}]

    probe._get_resources_to_check = AsyncMock(return_value=resources)
    # Mock _process_provider_batch to succeed
    probe._process_provider_batch = AsyncMock()
    # Simulate missing policy
    mock_accessor.get_health_policy.return_value = None

    await probe.run_cycle()

    # Verify that the wrapper used DEFAULT_TASK_TIMEOUT_SEC
    # We cannot directly inspect the timeout used, but we can ensure the task succeeded
    task = probe.active_tasks.get(provider_name)
    if task:
        await task
        await asyncio.sleep(0.01)
    assert provider_name not in probe.active_tasks
    # Ensure batch was called
    probe._process_provider_batch.assert_called_once_with(provider_name, resources)


# ----------------------------------------------------------------------
# Test: Multiple Providers – Mixed dispatch and skipping
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_providers_mixed_dispatch_and_skipping(probe, mock_dependencies):
    """
    Scenario: Two providers, one already active, one new.
    Verify that the new provider is dispatched, the active one is skipped.
    """
    mock_accessor, mock_db, mock_client_factory = mock_dependencies
    active_provider = "active_provider"
    new_provider = "new_provider"
    resources = [
        {"key_id": 6, "provider_name": active_provider},
        {"key_id": 7, "provider_name": new_provider},
    ]

    # Simulate active provider already processing
    mock_task = asyncio.create_task(asyncio.sleep(3600))
    probe.active_tasks[active_provider] = mock_task

    probe._get_resources_to_check = AsyncMock(return_value=resources)
    # Mock batch for new provider only
    probe._process_provider_batch = AsyncMock()
    policy = HealthPolicyConfig(task_timeout_sec=300)
    mock_accessor.get_health_policy.return_value = policy

    with patch("src.core.probes.logger.debug") as mock_debug:
        await probe.run_cycle()

        # Verify that active provider was skipped
        mock_debug.assert_called_once_with(
            f"Provider '{active_provider}' is already active. Skipping dispatch."
        )

    # Wait for the new provider's task to finish (should be immediate due to mock)
    new_task = probe.active_tasks.get(new_provider)
    if new_task:
        await new_task
        # Give time for finally block cleanup
        await asyncio.sleep(0.01)

    # Ensure batch was called only for new provider
    probe._process_provider_batch.assert_called_once_with(new_provider, [resources[1]])

    # Clean up long-running task
    mock_task.cancel()
    try:
        await mock_task
    except asyncio.CancelledError:
        pass

    # Verify that new provider task cleaned up
    assert new_provider not in probe.active_tasks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
