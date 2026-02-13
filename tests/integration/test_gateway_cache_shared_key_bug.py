#!/usr/bin/env python3

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.schemas import ModelInfo, ProviderConfig
from src.core.accessor import ConfigAccessor
from src.core.constants import ALL_MODELS_MARKER
from src.db.database import DatabaseManager
from src.services.gateway_cache import GatewayCache


@pytest.mark.asyncio
async def test_shared_key_status_bug_reproduction():
    """
    Reproduces a realistic bug scenario where shared keys fail to be found in the cache.

    This test simulates what happens when the ConfigAccessor cannot find the provider
    configuration (returns None). In this case, the get_key_from_pool method falls
    back to using the regular model-specific pool key ("test_provider:gpt-4") instead
    of the shared pool key ("test_provider:__ALL_MODELS__").

    Since the key is stored in the shared pool but the method looks in the model-specific
    pool, it returns None, demonstrating the bug where shared keys appear to be missing
    from the cache even though they exist.
    """
    # Arrange: Set up mocks
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.wait_for_schema_ready = AsyncMock()

    # Mock the keys repository within the db manager
    mock_keys_repo = MagicMock()
    mock_db_manager.keys = mock_keys_repo

    # Simulate the bug: accessor returns None for the provider config
    # This could happen if the provider name doesn't match exactly
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
    result = cache.get_key_from_pool(provider_name="test_provider", model_name="gpt-4")

    # Assert: The bug causes this to return None because the accessor returned None,
    # so it falls back to looking for "test_provider:gpt-4" instead of "test_provider:__ALL_MODELS__"
    assert result is None, (
        "Expected None due to the bug (accessor returning None), but got a key. "
        "This means the bug scenario is not being reproduced correctly."
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
    provider_config = ProviderConfig()
    provider_config.shared_key_status = True
    provider_config.models = {"gpt-4": ModelInfo(), "gpt-3.5-turbo": ModelInfo()}
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
    result = cache.get_key_from_pool(provider_name="test_provider", model_name="gpt-4")

    # Assert: This should return the key tuple when everything works correctly
    expected_result = (1, "test-key-123")
    assert result == expected_result, (
        f"Expected {expected_result} but got {result}. "
        "This indicates an issue with the shared key functionality."
    )
