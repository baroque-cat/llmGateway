#!/usr/bin/env python3

import collections
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.core.constants import ALL_MODELS_MARKER
from src.services.gateway.gateway_cache import GatewayCache


def test_constants_defined():
    """Verify the ALL_MODELS_MARKER constant is defined correctly."""
    assert ALL_MODELS_MARKER == "__ALL_MODELS__"


class TestGatewayCacheExcludeKeyIds:
    """Test get_key_from_pool with exclude_key_ids parameter."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor with default provider config (shared_key_status=False)."""
        accessor = MagicMock()
        provider_config = MagicMock()
        provider_config.shared_key_status = False
        accessor.get_provider.return_value = provider_config
        return accessor

    @pytest.fixture
    def mock_db_manager(self):
        return MagicMock()

    @pytest.fixture
    def cache(self, mock_accessor, mock_db_manager):
        return GatewayCache(mock_accessor, mock_db_manager)

    def test_get_key_from_pool_no_exclude(self, cache):
        """Test that get_key_from_pool returns key when exclude_key_ids is None."""
        # Setup a key pool as deque
        cache._key_pool["test:gpt-4"] = collections.deque([(1, "key1"), (2, "key2")])
        # Call without exclude_key_ids
        result = cache.get_key_from_pool("test", "gpt-4")
        assert result == (1, "key1")
        # Key should be rotated to the back
        assert list(cache._key_pool["test:gpt-4"]) == [(2, "key2"), (1, "key1")]

    def test_get_key_from_pool_exclude_specific_key(self, cache):
        """Test that get_key_from_pool skips keys in exclude_key_ids."""
        cache._key_pool["test:gpt-4"] = collections.deque(
            [(1, "key1"), (2, "key2"), (3, "key3")]
        )
        # Exclude key_id 2
        result = cache.get_key_from_pool("test", "gpt-4", exclude_key_ids={2})
        # Should return first non-excluded key (key_id 1)
        assert result == (1, "key1")
        # Rotation: key 2 is moved to back before being skipped, so order becomes
        # [(3, "key3"), (2, "key2"), (1, "key1")] after rotation of key1 (which is returned).
        # Let's compute: initial deque [1,2,3]
        # iteration 1: pop left 1, append right 1, not excluded -> return 1.
        # deque after operation: [2,3,1]
        # So final deque should be [2,3,1]
        assert list(cache._key_pool["test:gpt-4"]) == [
            (2, "key2"),
            (3, "key3"),
            (1, "key1"),
        ]

    def test_get_key_from_pool_all_excluded(self, cache):
        """Test that get_key_from_pool returns None when all keys are excluded."""
        cache._key_pool["test:gpt-4"] = collections.deque([(1, "key1"), (2, "key2")])
        result = cache.get_key_from_pool("test", "gpt-4", exclude_key_ids={1, 2})
        assert result is None
        # Pool should remain unchanged (no rotation because no key selected)
        # However, the algorithm will rotate each key to the back while skipping.
        # Let's trace: attempts = 2, first iteration: pop left 1, append right 1, excluded continue.
        # deque becomes [2,1]. second iteration: pop left 2, append right 2, excluded continue.
        # deque becomes [1,2]. So final deque order swapped.
        # We'll accept any order as long as same elements.
        assert set(cache._key_pool["test:gpt-4"]) == {(1, "key1"), (2, "key2")}

    def test_get_key_from_pool_exclude_with_shared_key_status(
        self, cache, mock_accessor
    ):
        """Test exclude_key_ids with shared_key_status enabled."""
        mock_provider_config = MagicMock()
        mock_provider_config.shared_key_status = True
        mock_accessor.get_provider.return_value = mock_provider_config
        # Setup virtual pool
        cache._key_pool["test:__ALL_MODELS__"] = collections.deque(
            [(1, "key1"), (2, "key2")]
        )
        # Exclude key_id 1
        result = cache.get_key_from_pool("test", "gpt-4", exclude_key_ids={1})
        assert result == (2, "key2")
        # Rotation should happen in the virtual pool: after returning key2, deque becomes [1,2]
        assert list(cache._key_pool["test:__ALL_MODELS__"]) == [
            (1, "key1"),
            (2, "key2"),
        ]

    def test_get_key_from_pool_empty_pool(self, cache):
        """Test that get_key_from_pool returns None when pool is empty."""
        cache._key_pool["test:gpt-4"] = collections.deque()
        result = cache.get_key_from_pool("test", "gpt-4")
        assert result is None

    def test_get_key_from_pool_single_key_excluded(self, cache):
        """Test when only one key exists and it's excluded."""
        cache._key_pool["test:gpt-4"] = collections.deque([(1, "key1")])
        result = cache.get_key_from_pool("test", "gpt-4", exclude_key_ids={1})
        assert result is None
        # Pool unchanged (after rotation, same element)
        assert list(cache._key_pool["test:gpt-4"]) == [(1, "key1")]

    def test_get_key_from_pool_exclude_key_ids_none(self, cache):
        """Test that exclude_key_ids being None works same as no exclude."""
        cache._key_pool["test:gpt-4"] = collections.deque([(1, "key1"), (2, "key2")])
        result = cache.get_key_from_pool("test", "gpt-4", exclude_key_ids=None)
        assert result == (1, "key1")
        assert list(cache._key_pool["test:gpt-4"]) == [(2, "key2"), (1, "key1")]


# ---------------------------------------------------------------------------
# Merged from test_gateway_cache_logging.py
# ---------------------------------------------------------------------------


class TestGatewayCacheLogging:
    """Tests for logging in GatewayCache."""

    @pytest.fixture
    def mock_accessor_logging(self):
        """Provide a mock ConfigAccessor."""
        return Mock()

    @pytest.fixture
    def mock_db_manager_logging(self):
        """Provide a mock DatabaseManager."""
        return Mock()

    @pytest.fixture
    def cache_logging(self, mock_accessor_logging, mock_db_manager_logging):
        """Create a GatewayCache instance with mocked dependencies."""
        return GatewayCache(mock_accessor_logging, mock_db_manager_logging)

    @pytest.mark.asyncio
    async def test_cache_refresh_log_level(
        self, cache_logging, mock_db_manager_logging
    ):
        """Verify that cache refresh logs at DEBUG level on success."""
        # Mock the database query to return some valid keys (async method)

        mock_db_manager_logging.keys.get_all_valid_keys_for_caching = AsyncMock(
            return_value=[
                {
                    "key_id": 1,
                    "provider_name": "openai",
                    "model_name": "gpt-4",
                    "key_value": "sk-xxx",
                }
            ]
        )
        with patch("src.services.gateway.gateway_cache.logger") as mock_logger:
            await cache_logging.refresh_key_pool()
            # Collect all calls to logger methods
            print(f"All calls: {mock_logger.method_calls}")
            # Both start and success logs should be at DEBUG level
            # Verify debug was called twice
            assert mock_logger.debug.call_count == 2
            # Get both calls
            debug_calls = mock_logger.debug.call_args_list
            # First call should be the start message
            assert "Refreshing key pool cache from database" in debug_calls[0][0][0]
            # Second call should be the success message
            assert "Key pool cache refreshed successfully" in debug_calls[1][0][0]
            # Info should NOT be called (all logs are DEBUG)
            mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_shared_key_removal_log(self, cache_logging, mock_accessor_logging):
        """Verify that removing a shared key logs appropriately."""
        # Mock provider config with shared_key_status = True
        mock_provider_config = Mock()
        mock_provider_config.shared_key_status = True
        mock_accessor_logging.get_provider.return_value = mock_provider_config
        # Pre-populate a key in the pool
        cache_logging._key_pool["openai:__ALL_MODELS__"] = [(1, "sk-xxx")]
        with patch("src.services.gateway.gateway_cache.logger") as mock_logger:
            await cache_logging.remove_key_from_pool("openai", "gpt-4", 1)
            # Should log DEBUG about removing shared key (no INFO logs)
            mock_logger.info.assert_not_called()
            # Find the call about shared key in debug logs
            shared_call = None
            for call in mock_logger.debug.call_args_list:
                if "shared key_id" in call[0][0]:
                    shared_call = call
                    break
            assert shared_call is not None
            assert "Removing shared key_id 1 from virtual pool" in shared_call[0][0]
            assert "openai:shared" in shared_call[0][0]

    @pytest.mark.asyncio
    async def test_granular_key_removal_log(self, cache_logging, mock_accessor_logging):
        """Verify that removing a non-shared key logs granular removal."""
        mock_provider_config = Mock()
        mock_provider_config.shared_key_status = False
        mock_accessor_logging.get_provider.return_value = mock_provider_config
        cache_logging._key_pool["openai:gpt-4"] = [(1, "sk-xxx")]
        with patch("src.services.gateway.gateway_cache.logger") as mock_logger:
            await cache_logging.remove_key_from_pool("openai", "gpt-4", 1)
            # Should log DEBUG about removing from specific pool (no INFO logs)
            mock_logger.info.assert_not_called()
            granular_call = None
            for call in mock_logger.debug.call_args_list:
                if "Removed failed key_id" in call[0][0]:
                    granular_call = call
                    break
            assert granular_call is not None
            assert "Removed failed key_id 1 from live cache pool" in granular_call[0][0]
            assert "openai:gpt-4" in granular_call[0][0]
