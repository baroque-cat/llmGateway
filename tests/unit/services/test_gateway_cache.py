#!/usr/bin/env python3

import collections
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.services.gateway.gateway_cache import GatewayCache


class TestGatewayCacheExcludeKeyIds:
    """Test get_key_from_pool with exclude_key_ids parameter."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor."""
        accessor = MagicMock()
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
        cache._key_pool["test"] = collections.deque([(1, "key1"), (2, "key2")])
        # Call without exclude_key_ids
        result = cache.get_key_from_pool("test")
        assert result == (1, "key1")
        # Key should be rotated to the back
        assert list(cache._key_pool["test"]) == [(2, "key2"), (1, "key1")]

    def test_get_key_from_pool_exclude_specific_key(self, cache):
        """Test that get_key_from_pool skips keys in exclude_key_ids."""
        cache._key_pool["test"] = collections.deque(
            [(1, "key1"), (2, "key2"), (3, "key3")]
        )
        # Exclude key_id 2
        result = cache.get_key_from_pool("test", exclude_key_ids={2})
        # Should return first non-excluded key (key_id 1)
        assert result == (1, "key1")
        # Rotation: key 2 is moved to back before being skipped, so order becomes
        # [(3, "key3"), (2, "key2"), (1, "key1")] after rotation of key1 (which is returned).
        # Let's compute: initial deque [1,2,3]
        # iteration 1: pop left 1, append right 1, not excluded -> return 1.
        # deque after operation: [2,3,1]
        # So final deque should be [2,3,1]
        assert list(cache._key_pool["test"]) == [
            (2, "key2"),
            (3, "key3"),
            (1, "key1"),
        ]

    def test_get_key_from_pool_all_excluded(self, cache):
        """Test that get_key_from_pool returns None when all keys are excluded."""
        cache._key_pool["test"] = collections.deque([(1, "key1"), (2, "key2")])
        result = cache.get_key_from_pool("test", exclude_key_ids={1, 2})
        assert result is None
        # Pool should remain unchanged (no rotation because no key selected)
        # However, the algorithm will rotate each key to the back while skipping.
        # Let's trace: attempts = 2, first iteration: pop left 1, append right 1, excluded continue.
        # deque becomes [2,1]. second iteration: pop left 2, append right 2, excluded continue.
        # deque becomes [1,2]. So final deque order swapped.
        # We'll accept any order as long as same elements.
        assert set(cache._key_pool["test"]) == {(1, "key1"), (2, "key2")}

    def test_get_key_from_pool_empty_pool(self, cache):
        """Test that get_key_from_pool returns None when pool is empty."""
        cache._key_pool["test"] = collections.deque()
        result = cache.get_key_from_pool("test")
        assert result is None

    def test_get_key_from_pool_single_key_excluded(self, cache):
        """Test when only one key exists and it's excluded."""
        cache._key_pool["test"] = collections.deque([(1, "key1")])
        result = cache.get_key_from_pool("test", exclude_key_ids={1})
        assert result is None
        # Pool unchanged (after rotation, same element)
        assert list(cache._key_pool["test"]) == [(1, "key1")]

    def test_get_key_from_pool_exclude_key_ids_none(self, cache):
        """Test that exclude_key_ids being None works same as no exclude."""
        cache._key_pool["test"] = collections.deque([(1, "key1"), (2, "key2")])
        result = cache.get_key_from_pool("test", exclude_key_ids=None)
        assert result == (1, "key1")
        assert list(cache._key_pool["test"]) == [(2, "key2"), (1, "key1")]


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
    async def test_key_removal_log(self, cache_logging):
        """Verify that removing a key logs appropriately."""
        cache_logging._key_pool["openai"] = collections.deque([(1, "sk-xxx")])
        with patch("src.services.gateway.gateway_cache.logger") as mock_logger:
            await cache_logging.remove_key_from_pool("openai", 1)
            # Should log DEBUG about removing key (no INFO logs)
            mock_logger.info.assert_not_called()
            removal_call = None
            for call in mock_logger.debug.call_args_list:
                if "Removed failed key_id" in call[0][0]:
                    removal_call = call
                    break
            assert removal_call is not None
            assert (
                "Removed failed key_id 1 from live cache pool 'openai'"
                in removal_call[0][0]
            )


# ---------------------------------------------------------------------------
# Coverage map required scenario names — standalone test functions
# ---------------------------------------------------------------------------


def test_pool_key_is_provider_name_only():
    """Verify pool key is just provider_name, no model_name suffix."""
    mock_accessor = MagicMock()
    mock_db_manager = MagicMock()
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Populate a pool manually — keyed by provider_name only
    cache._key_pool["my-provider"] = collections.deque([(1, "key1")])

    # Verify the pool is accessible by provider name (no ":{model_name}" suffix)
    assert "my-provider" in cache._key_pool
    assert len(cache._key_pool["my-provider"]) == 1
    assert cache._key_pool["my-provider"][0] == (1, "key1")

    # Also verify via get_key_from_pool (no model_name involved)
    result = cache.get_key_from_pool("my-provider")
    assert result == (1, "key1")


@pytest.mark.asyncio
async def test_multiple_models_share_one_pool():
    """Verify 3 keys with different model_names all go into the same provider pool."""
    mock_accessor = MagicMock()
    mock_db_manager = MagicMock()

    # Mock refresh_key_pool to load records with different model_names
    mock_db_manager.keys.get_all_valid_keys_for_caching = AsyncMock(
        return_value=[
            {
                "key_id": 1,
                "provider_name": "openai",
                "model_name": "gpt-4",
                "key_value": "sk-a",
            },
            {
                "key_id": 2,
                "provider_name": "openai",
                "model_name": "gpt-4",
                "key_value": "sk-b",
            },
            {
                "key_id": 3,
                "provider_name": "openai",
                "model_name": "__ALL_MODELS__",
                "key_value": "sk-c",
            },
        ]
    )
    cache = GatewayCache(mock_accessor, mock_db_manager)
    await cache.refresh_key_pool()

    # All 3 keys should be in the single pool keyed by provider_name only
    assert "openai" in cache._key_pool
    assert len(cache._key_pool["openai"]) == 3
    key_ids = {info[0] for info in cache._key_pool["openai"]}
    assert key_ids == {1, 2, 3}
    # No model-specific pool keys exist
    assert len(cache._key_pool) == 1


@pytest.mark.asyncio
async def test_remove_key_from_pool_by_provider_and_key_id():
    """Verify remove_key_from_pool() removes the key and pool size decreases."""
    mock_accessor = MagicMock()
    mock_db_manager = MagicMock()
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Populate pool with 3 keys
    cache._key_pool["my-provider"] = collections.deque(
        [(10, "k10"), (42, "k42"), (99, "k99")]
    )
    assert len(cache._key_pool["my-provider"]) == 3

    # Remove key_id 42
    await cache.remove_key_from_pool("my-provider", key_id=42)

    # Verify pool size decreased and key 42 is gone
    assert len(cache._key_pool["my-provider"]) == 2
    remaining_ids = {info[0] for info in cache._key_pool["my-provider"]}
    assert remaining_ids == {10, 99}
    assert 42 not in remaining_ids


def test_get_key_from_pool_without_model_name():
    """Test get_key_from_pool works correctly without a model_name argument."""
    mock_accessor = MagicMock()
    mock_db_manager = MagicMock()
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Populate the pool
    cache._key_pool["test"] = collections.deque([(1, "key1")])

    # Call without model_name arg (only provider_name)
    result = cache.get_key_from_pool("test")
    assert result == (1, "key1")


def test_get_key_from_pool_returns_none_when_empty():
    """Test get_key_from_pool returns None for a nonexistent pool."""
    mock_accessor = MagicMock()
    mock_db_manager = MagicMock()
    cache = GatewayCache(mock_accessor, mock_db_manager)

    # Don't populate the pool at all
    result = cache.get_key_from_pool("nonexistent")
    assert result is None
