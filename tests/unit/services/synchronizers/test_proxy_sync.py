#!/usr/bin/env python3

"""
Unit tests for proxy synchronization functionality.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.accessor import ConfigAccessor
from src.db.database import DatabaseManager
from src.services.synchronizers.proxy_sync import ProxySyncer


def test_proxy_syncer_get_resource_type():
    """Test that ProxySyncer returns the correct resource type identifier."""
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    syncer = ProxySyncer(mock_accessor, mock_db_manager)
    assert syncer.get_resource_type() == "proxies"


@pytest.mark.asyncio
async def test_proxy_syncer_apply_state_empty():
    """Test that ProxySyncer.apply_state handles empty desired state."""
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.proxies = MagicMock()
    mock_db_manager.proxies.sync = AsyncMock()

    syncer = ProxySyncer(mock_accessor, mock_db_manager)

    provider_id_map = {}
    desired_state = {}  # No providers

    await syncer.apply_state(provider_id_map, desired_state)

    # Should not raise, and sync should not be called
    mock_db_manager.proxies.sync.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_syncer_apply_state_with_provider():
    """Test that ProxySyncer.apply_state calls sync with correct arguments."""
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.proxies = MagicMock()
    mock_db_manager.proxies.sync = AsyncMock()

    syncer = ProxySyncer(mock_accessor, mock_db_manager)

    provider_id_map = {"provider_a": 1}
    desired_state = {
        "provider_a": {
            "proxies_from_files": {"http://proxy1:8080", "http://proxy2:8080"}
        }
    }

    await syncer.apply_state(provider_id_map, desired_state)

    mock_db_manager.proxies.sync.assert_called_once_with(
        provider_name="provider_a",
        provider_id=1,
        proxies_from_file={"http://proxy1:8080", "http://proxy2:8080"},
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
