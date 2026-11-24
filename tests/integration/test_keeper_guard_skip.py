"""Integration tests for NetworkGuard skip behavior in keeper probe cycle.

Verifies that:
- When NetworkGuard is DOWN and enforcing, IResourceProbe.run_cycle() returns early
- _get_resources_to_check() is not called
- A warning log message is emitted
- No DB operations occur
"""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.schemas import DatabaseConfig, DatabaseRetryConfig, NetworkGuardConfig
from src.core.models import CheckResult
from src.core.network_guard import NetworkGuard, set_network_guard
from src.core.probes import IResourceProbe


class GuardSkipProbe(IResourceProbe):
    """Concrete test double for IResourceProbe."""

    def __init__(self, accessor, db_manager, client_factory):
        super().__init__(accessor, db_manager, client_factory)
        self.get_resources_called = False
        self.check_resource_called = False
        self.update_status_called = False

    async def _get_resources_to_check(self) -> list[Any]:
        self.get_resources_called = True
        raise AssertionError(
            "_get_resources_to_check should not be called when guard is DOWN"
        )

    async def _check_resource(self, resource: dict[str, Any]) -> CheckResult:
        self.check_resource_called = True
        raise AssertionError("_check_resource should not be called when guard is DOWN")

    async def _update_resource_status(
        self, resource: dict[str, Any], result: CheckResult
    ) -> None:
        self.update_status_called = True
        raise AssertionError(
            "_update_resource_status should not be called when guard is DOWN"
        )


@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for TestProbe."""
    mock_db = MagicMock()
    mock_db.keys.update_status = AsyncMock()
    mock_db.keys.get_keys_to_check = AsyncMock(return_value=[])
    mock_http = MagicMock()
    mock_http.get_client_for_provider = AsyncMock()
    mock_accessor = MagicMock()
    mock_accessor.get_keeper_concurrency.return_value = 10
    mock_accessor.get_database_config.return_value = DatabaseConfig(
        retry=DatabaseRetryConfig(
            max_attempts=3,
            base_delay_sec=0.1,
            backoff_factor=2.0,
            jitter=False,
        )
    )
    return mock_accessor, mock_db, mock_http


@pytest.fixture
def guard_config(tmp_path):
    """Create a NetworkGuardConfig for testing."""
    return NetworkGuardConfig(
        enabled=True,
        mode="pause",
        probe_urls=[],
        probe_interval_sec=30,
        probe_connect_timeout_sec=3.0,
        probe_total_timeout_sec=5.0,
        min_probe_successes=2,
        fail_threshold=3,
        passive_window_sec=60,
        passive_min_providers=3,
        passive_min_failures=6,
        startup_probe=True,
        auto_recover=False,
        marker_path=str(tmp_path / "state.json"),
    )


@pytest.mark.asyncio
async def test_run_cycle_skips_when_guard_down(mock_dependencies, guard_config, caplog):
    """run_cycle() returns early when guard is DOWN and enforcing."""
    mock_accessor, mock_db, mock_http = mock_dependencies

    # Install a DOWN guard
    guard = NetworkGuard(guard_config, source="keeper")
    await guard.mark_down("test_reason", {"test": "evidence"})
    set_network_guard(guard)

    try:
        # Create probe and run cycle
        probe = GuardSkipProbe(mock_accessor, mock_db, mock_http)

        with caplog.at_level(logging.WARNING):
            await probe.run_cycle()

        # Verify _get_resources_to_check was not called
        assert probe.get_resources_called is False
        assert probe.check_resource_called is False
        assert probe.update_status_called is False

        # Verify warning log was emitted
        assert any(
            "Network guard is DOWN" in record.message
            and "skipping resource check cycle" in record.message
            for record in caplog.records
        )

        # Verify no DB operations occurred
        mock_db.keys.get_keys_to_check.assert_not_awaited()
        mock_db.keys.update_status.assert_not_awaited()
    finally:
        # Clean up
        set_network_guard(None)


@pytest.mark.asyncio
async def test_run_cycle_proceeds_when_guard_up(mock_dependencies, guard_config):
    """run_cycle() proceeds normally when guard is UP."""
    mock_accessor, mock_db, mock_http = mock_dependencies

    # Install an UP guard (or no guard)
    guard = NetworkGuard(guard_config, source="keeper")
    # Don't mark down, so it's UP
    set_network_guard(guard)

    try:
        # Create probe and run cycle
        probe = GuardSkipProbe(mock_accessor, mock_db, mock_http)

        # Create a custom async function that sets the flag and returns empty list
        async def mock_get_resources():
            probe.get_resources_called = True
            return []

        probe._get_resources_to_check = mock_get_resources

        await probe.run_cycle()

        # Verify _get_resources_to_check was called
        assert probe.get_resources_called is True
    finally:
        # Clean up
        set_network_guard(None)


@pytest.mark.asyncio
async def test_run_cycle_proceeds_when_guard_log_mode(mock_dependencies, guard_config):
    """run_cycle() proceeds when guard is DOWN but in log mode (not enforcing)."""
    mock_accessor, mock_db, mock_http = mock_dependencies

    # Install a DOWN guard in log mode
    config_log = guard_config.model_copy(update={"mode": "log"})
    guard = NetworkGuard(config_log, source="keeper")
    await guard.mark_down("test_reason", {})
    set_network_guard(guard)

    try:
        # Create probe and run cycle
        probe = GuardSkipProbe(mock_accessor, mock_db, mock_http)

        # Create a custom async function that sets the flag and returns empty list
        async def mock_get_resources():
            probe.get_resources_called = True
            return []

        probe._get_resources_to_check = mock_get_resources

        await probe.run_cycle()

        # Verify _get_resources_to_check was called (log mode doesn't block)
        assert probe.get_resources_called is True
    finally:
        # Clean up
        set_network_guard(None)


@pytest.mark.asyncio
async def test_run_cycle_proceeds_when_no_guard(mock_dependencies):
    """run_cycle() proceeds normally when no guard is installed."""
    mock_accessor, mock_db, mock_http = mock_dependencies

    # No guard installed
    set_network_guard(None)

    # Create probe and run cycle
    probe = GuardSkipProbe(mock_accessor, mock_db, mock_http)

    # Create a custom async function that sets the flag and returns empty list
    async def mock_get_resources():
        probe.get_resources_called = True
        return []

    probe._get_resources_to_check = mock_get_resources

    await probe.run_cycle()

    # Verify _get_resources_to_check was called
    assert probe.get_resources_called is True
