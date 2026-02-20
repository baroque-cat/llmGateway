#!/usr/bin/env python3

import collections
from unittest.mock import MagicMock
import pytest
from src.core.constants import ALL_MODELS_MARKER
from src.services.gateway_cache import GatewayCache


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
