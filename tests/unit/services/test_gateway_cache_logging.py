"""
Unit tests for logging behavior in gateway_cache.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.services.gateway_cache import GatewayCache


class TestGatewayCacheLogging:
    """Tests for logging in GatewayCache."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor."""
        return Mock()

    @pytest.fixture
    def mock_db_manager(self):
        """Provide a mock DatabaseManager."""
        return Mock()

    @pytest.fixture
    def cache(self, mock_accessor, mock_db_manager):
        """Create a GatewayCache instance with mocked dependencies."""
        return GatewayCache(mock_accessor, mock_db_manager)

    @pytest.mark.asyncio
    async def test_cache_refresh_log_level(self, cache, mock_db_manager):
        """Verify that cache refresh logs at DEBUG level on success."""
        # Mock the database query to return some valid keys (async method)
        from unittest.mock import AsyncMock

        mock_db_manager.keys.get_all_valid_keys_for_caching = AsyncMock(
            return_value=[
                {
                    "key_id": 1,
                    "provider_name": "openai",
                    "model_name": "gpt-4",
                    "key_value": "sk-xxx",
                }
            ]
        )
        with patch("src.services.gateway_cache.logger") as mock_logger:
            await cache.refresh_key_pool()
            # Collect all calls to logger methods
            print(f"All calls: {mock_logger.method_calls}")
            # Debug log should be called
            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args[0][0]
            assert "Key pool cache refreshed successfully" in call_args
            # Info log should also be called at start
            mock_logger.info.assert_called_once()
            info_call = mock_logger.info.call_args[0][0]
            assert "Refreshing key pool cache from database" in info_call

    @pytest.mark.asyncio
    async def test_shared_key_removal_log(self, cache, mock_accessor):
        """Verify that removing a shared key logs appropriately."""
        # Mock provider config with shared_key_status = True
        mock_provider_config = Mock()
        mock_provider_config.shared_key_status = True
        mock_accessor.get_provider.return_value = mock_provider_config
        # Pre-populate a key in the pool
        cache._key_pool["openai:__ALL_MODELS__"] = [(1, "sk-xxx")]
        with patch("src.services.gateway_cache.logger") as mock_logger:
            await cache.remove_key_from_pool("openai", "gpt-4", 1)
            # Should log info about removing shared key
            mock_logger.info.assert_called()
            # Find the call about shared key
            shared_call = None
            for call in mock_logger.info.call_args_list:
                if "shared key_id" in call[0][0]:
                    shared_call = call
                    break
            assert shared_call is not None
            assert "Removing shared key_id 1 from virtual pool" in shared_call[0][0]
            assert "openai:shared" in shared_call[0][0]

    @pytest.mark.asyncio
    async def test_granular_key_removal_log(self, cache, mock_accessor):
        """Verify that removing a non-shared key logs granular removal."""
        mock_provider_config = Mock()
        mock_provider_config.shared_key_status = False
        mock_accessor.get_provider.return_value = mock_provider_config
        cache._key_pool["openai:gpt-4"] = [(1, "sk-xxx")]
        with patch("src.services.gateway_cache.logger") as mock_logger:
            await cache.remove_key_from_pool("openai", "gpt-4", 1)
            # Should log info about removing from specific pool
            mock_logger.info.assert_called()
            granular_call = None
            for call in mock_logger.info.call_args_list:
                if "Removed failed key_id" in call[0][0]:
                    granular_call = call
                    break
            assert granular_call is not None
            assert "Removed failed key_id 1 from live cache pool" in granular_call[0][0]
            assert "openai:gpt-4" in granular_call[0][0]
