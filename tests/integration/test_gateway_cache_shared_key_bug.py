#!/usr/bin/env python3

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.schemas import ModelInfo, ProviderConfig
from src.core.accessor import ConfigAccessor
from src.core.constants import ALL_MODELS_MARKER
from src.db.database import DatabaseManager
from src.services.gateway.gateway_cache import GatewayCache


@pytest.mark.asyncio
async def test_shared_key_status_bug_reproduction():
    """
    Verify that the shared-key bug (accessor returning None causing wrong pool lookup)
    has been fixed. In the current architecture, get_key_from_pool uses a flat
    provider-name-based pool key, so even when the accessor returns None,
    the key is still found correctly in the pool.
    """
    # Arrange: Set up mocks
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.wait_for_schema_ready = AsyncMock()

    # Mock the keys repository within the db manager
    mock_keys_repo = MagicMock()
    mock_db_manager.keys = mock_keys_repo

    # Simulate the old bug: accessor returns None for the provider config
    mock_accessor.get_provider.return_value = None

    # Mock database to return a valid key with model_name="__ALL_MODELS__"
    mock_valid_keys = [
        {
            "key_id": 1,
            "provider_name": "test_provider",
            "model_name": ALL_MODELS_MARKER,
            "key_value": "test-key-123",
        }
    ]
    mock_keys_repo.get_all_valid_keys_for_caching = AsyncMock(
        return_value=mock_valid_keys
    )

    # Initialize GatewayCache
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Act: Refresh the key pool and try to get a key
    await cache.refresh_key_pool()
    result = cache.get_key_from_pool(provider_name="test_provider")

    # Assert: The bug is fixed — get_key_from_pool now uses a flat provider-name
    # pool key, so it finds the key regardless of accessor state.
    expected_result = (1, "test-key-123")
    assert result == expected_result, (
        f"Expected {expected_result} but got {result}. "
        "The shared key bug has been fixed by the flat provider pool architecture."
    )


@pytest.mark.asyncio
async def test_shared_key_status_working_correctly():
    """
    Test that verifies the correct behavior when everything works as expected.

    This test demonstrates that when the ConfigAccessor properly returns the
    provider configuration with shared_key_status=True, the get_key_from_pool
    method correctly retrieves keys from the shared pool.
    """
    # Arrange: Set up mocks
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.wait_for_schema_ready = AsyncMock()

    # Mock the keys repository within the db manager
    mock_keys_repo = MagicMock()
    mock_db_manager.keys = mock_keys_repo

    # Mock provider config with shared_key_status=True
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.shared_key_status = True
    provider_config.default_model = {"gpt-4": ModelInfo(), "gpt-3.5-turbo": ModelInfo()}
    mock_accessor.get_provider.return_value = provider_config

    # Mock database to return a valid key with model_name="__ALL_MODELS__"
    mock_valid_keys = [
        {
            "key_id": 1,
            "provider_name": "test_provider",
            "model_name": ALL_MODELS_MARKER,
            "key_value": "test-key-123",
        }
    ]
    mock_keys_repo.get_all_valid_keys_for_caching = AsyncMock(
        return_value=mock_valid_keys
    )

    # Initialize GatewayCache
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Act: Refresh the key pool and try to get a key
    await cache.refresh_key_pool()
    result = cache.get_key_from_pool(provider_name="test_provider")

    # Assert: This should return the key tuple when everything works correctly
    expected_result = (1, "test-key-123")
    assert result == expected_result, (
        f"Expected {expected_result} but got {result}. "
        "This indicates an issue with the shared key functionality."
    )
