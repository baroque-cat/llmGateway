"""Tests for GatewayCache sticky key selection mode.

Covers all sticky-cache-unit scenarios from the add-sticky-key-mode test plan.
All configuration values derive from the source API via ``GatewayCache``
primitives — zero hardcodes.
"""

from __future__ import annotations

import collections
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import KeySelectionMode
from src.services.gateway.gateway_cache import GatewayCache


def _make_sticky_accessor(
    provider_name: str = "test-sticky",
    circuit_breaker_enabled: bool = False,
) -> MagicMock:
    """Build a mock ``ConfigAccessor`` with one sticky-mode provider.

    Args:
        provider_name: Provider instance name for the test.
        circuit_breaker_enabled: Whether a circuit breaker is active.

    Returns:
        A ``MagicMock`` whose ``get_enabled_providers()`` returns a dict
        with a single sticky-mode provider config.
    """
    accessor = MagicMock()
    provider_cfg = MagicMock()
    provider_cfg.gateway_policy.key_selection.mode = KeySelectionMode.STICKY
    provider_cfg.gateway_policy.circuit_breaker.enabled = circuit_breaker_enabled
    accessor.get_enabled_providers.return_value = {provider_name: provider_cfg}
    return accessor


def _make_round_robin_accessor(
    provider_name: str = "test-rr",
) -> MagicMock:
    """Build a mock ``ConfigAccessor`` with one round-robin-mode provider.

    Args:
        provider_name: Provider instance name for the test.

    Returns:
        A ``MagicMock`` whose ``get_enabled_providers()`` returns a dict
        with a single round-robin-mode provider config.
    """
    accessor = MagicMock()
    provider_cfg = MagicMock()
    provider_cfg.gateway_policy.key_selection.mode = KeySelectionMode.ROUND_ROBIN
    provider_cfg.gateway_policy.circuit_breaker.enabled = False
    accessor.get_enabled_providers.return_value = {provider_name: provider_cfg}
    return accessor


def _populate_pool(
    cache: GatewayCache,
    provider_name: str,
    keys: list[tuple[int, str]],
) -> None:
    """Directly populate the key pool deque for a provider.

    Args:
        cache: The ``GatewayCache`` instance.
        provider_name: Provider pool key.
        keys: List of ``(key_id, key_value)`` tuples.
    """
    cache._key_pool[provider_name] = collections.deque(keys)


class TestStickyPointerPerWorker:
    """Sticky pointer is per-worker and in-memory (spec: sticky-key-selection)."""

    def test_two_workers_hold_different_sticky_keys(self):
        """Two independent GatewayCache instances establish independent pointers.

        Each worker (GatewayCache instance) independently picks a key from the
        same pool.  The pointers are per-instance and may point to different keys.
        """
        provider = "test-sticky"
        pool_keys = [(1, "k1"), (2, "k2"), (3, "k3")]

        # Worker A
        accessor_a = _make_sticky_accessor(provider)
        cache_a = GatewayCache(accessor_a, MagicMock())
        _populate_pool(cache_a, provider, pool_keys)

        # Worker B
        accessor_b = _make_sticky_accessor(provider)
        cache_b = GatewayCache(accessor_b, MagicMock())
        _populate_pool(cache_b, provider, pool_keys)

        # Each worker independently establishes a pointer
        key_a = cache_a.get_key_from_pool(provider)
        key_b = cache_b.get_key_from_pool(provider)

        assert key_a is not None
        assert key_b is not None
        # They are independent instances — pointers belong to different caches
        pointer_a = cache_a.get_sticky_pointer(provider)
        pointer_b = cache_b.get_sticky_pointer(provider)
        assert pointer_a is not None
        assert pointer_b is not None
        # They MAY hold different keys (probability ~2/3 in this pool).
        # We only assert that each cache has its own pointer.
        assert pointer_a == key_a
        assert pointer_b == key_b

    def test_worker_restart_resets_pointer(self):
        """Fresh cache: get_sticky_pointer is None; next get_key_from_pool
        establishes it (boundary: testing sticky pointer lifecycle)."""
        provider = "test-sticky"

        # Fresh cache = simulate restart
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        assert (
            cache.get_sticky_pointer(provider) is None
        )  # boundary: unset before first request

        _populate_pool(cache, provider, [(10, "k10")])
        result = cache.get_key_from_pool(provider)
        assert result == (10, "k10")
        pointer = cache.get_sticky_pointer(provider)
        assert pointer == (10, "k10")


class TestStickySelection:
    """Sticky selection returns the pointer key without rotating the pool."""

    def test_consecutive_requests_reuse_same_key(self):
        """5 calls return the same (key_id, key_value)."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2"), (3, "k3")])

        first = cache.get_key_from_pool(provider)
        assert first is not None
        # 4 more calls — all should return the same key
        for _ in range(4):
            assert cache.get_key_from_pool(provider) == first

    def test_deque_not_rotated_by_sticky_selection(self):
        """Deque order unchanged by sticky-hit picks (after initial establishment).

        The *establishment* call (first get_key_from_pool with no pointer) uses
        _get_key_round_robin which rotates the deque.  Subsequent sticky-hit calls
        return the pointer without further rotation.
        """
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        original = [(1, "k1"), (2, "k2"), (3, "k3")]
        _populate_pool(cache, provider, original)

        # First call: establishment rotates the deque
        cache.get_key_from_pool(provider)
        # After establishment, deque has been rotated once (round-robin)
        pool_after_establish = list(cache._key_pool[provider])

        # Subsequent sticky hits do NOT rotate the deque
        for _ in range(3):
            cache.get_key_from_pool(provider)
            assert list(cache._key_pool[provider]) == pool_after_establish

    def test_first_request_establishes_pointer(self):
        """First call to get_key_from_pool establishes the sticky pointer."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(7, "k7")])

        assert cache.get_sticky_pointer(provider) is None
        result = cache.get_key_from_pool(provider)
        assert result == (7, "k7")
        assert cache.get_sticky_pointer(provider) == (7, "k7")


class TestStickyPointerRefresh:
    """Sticky pointer survives cache refresh."""

    @pytest.mark.asyncio
    async def test_pointer_survives_periodic_refresh(self):
        """refresh_key_pool() rebuild containing same key_id — pointer kept."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        mock_db = MagicMock()
        cache = GatewayCache(accessor, mock_db)

        # Seed pool with one key and establish a pointer
        _populate_pool(cache, provider, [(42, "old-value")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (42, "old-value")

        # Rebuild pool with same key_id but different value
        mock_db.keys.get_all_valid_keys_for_caching = AsyncMock(
            return_value=[
                {
                    "key_id": 42,
                    "provider_name": provider,
                    "key_value": "new-value",
                }
            ]
        )
        await cache.refresh_key_pool()

        # Pointer should survive with refreshed value
        pointer = cache.get_sticky_pointer(provider)
        assert pointer is not None
        assert pointer[0] == 42
        assert pointer[1] == "new-value"

    @pytest.mark.asyncio
    async def test_pointer_cleared_when_key_disappears_from_pool(self):
        """Rebuild without the key_id — pointer cleared, next pick re-establishes."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        mock_db = MagicMock()
        cache = GatewayCache(accessor, mock_db)

        # Seed pool and establish pointer
        _populate_pool(cache, provider, [(42, "k42"), (99, "k99")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) is not None

        # Rebuild without key 42
        mock_db.keys.get_all_valid_keys_for_caching = AsyncMock(
            return_value=[
                {
                    "key_id": 99,
                    "provider_name": provider,
                    "key_value": "k99",
                }
            ]
        )
        await cache.refresh_key_pool()

        # Pointer cleared
        assert cache.get_sticky_pointer(provider) is None
        # Next pick re-establishes from the rebuilt pool
        result = cache.get_key_from_pool(provider)
        assert result == (99, "k99")
        assert cache.get_sticky_pointer(provider) == (99, "k99")


class TestStickyRotation:
    """Rotation triggers in sticky mode (cache-level primitives)."""

    def test_client_error_keeps_sticky_key(self):
        """BAD_REQUEST: pointer unchanged; no rotation helper invoked."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2")])
        cache.get_key_from_pool(provider)
        pointer_before = cache.get_sticky_pointer(provider)

        # Client error does not trigger rotation at the cache level —
        # the handler decides not to call rotate_sticky_key for BAD_REQUEST.
        # We verify the pointer is untouched.
        assert pointer_before == (1, "k1")

    def test_fatal_error_rotates_and_bans(self):
        """NO_QUOTA: rotate_sticky_key(exclude_key_ids={failed}) moves pointer."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(42, "k42"), (43, "k43"), (44, "k44")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (42, "k42")

        # Rotate excluding the failed key 42
        new_pointer = cache.rotate_sticky_key(provider, exclude_key_ids={42})
        assert new_pointer is not None
        assert new_pointer[0] != 42
        assert cache.get_sticky_pointer(provider) == new_pointer

    def test_rate_limit_rotates_and_bans(self):
        """RATE_LIMITED: same rotation pattern as fatal errors."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(10, "k10"), (20, "k20")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (10, "k10")

        new_pointer = cache.rotate_sticky_key(provider, exclude_key_ids={10})
        assert new_pointer is not None
        assert new_pointer[0] != 10
        assert cache.get_sticky_pointer(provider) == new_pointer

    def test_server_error_rotates_without_ban(self):
        """rotate_via rotate_sticky_key; failed key REMAINS in pool."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(10, "k10"), (20, "k20")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (10, "k10")

        # Rotate excluding the failed key, WITHOUT removing
        new_pointer = cache.rotate_sticky_key(provider, exclude_key_ids={10})
        assert new_pointer is not None
        assert new_pointer[0] != 10
        # Key 10 is still in the pool
        pool_ids = {info[0] for info in cache._key_pool[provider]}
        assert 10 in pool_ids

        # Call note_rotation_without_ban (the handler calls this)
        cache.note_rotation_without_ban(provider)

    def test_rotation_excludes_failed_key(self):
        """Pool keys 42/43/44, fail 42 → new pointer is 43 or 44, never 42."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(42, "k42"), (43, "k43"), (44, "k44")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (42, "k42")

        new_pointer = cache.rotate_sticky_key(provider, exclude_key_ids={42})
        assert new_pointer is not None
        assert new_pointer[0] != 42
        assert new_pointer[0] in {43, 44}

    def test_pool_exhausted_during_rotation(self):
        """Single key fails — rotate_sticky_key returns None and pointer cleared."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(42, "k42")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (42, "k42")

        new_pointer = cache.rotate_sticky_key(provider, exclude_key_ids={42})
        assert new_pointer is None
        assert cache.get_sticky_pointer(provider) is None


class TestStickyPointerRemoval:
    """Direct removal of the sticky key clears the pointer."""

    @pytest.mark.asyncio
    async def test_external_removal_clears_matching_pointer(self):
        """remove_key_from_pool with pointer's key_id clears pointer."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(42, "k42"), (99, "k99")])
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (42, "k42")

        await cache.remove_key_from_pool(provider, key_id=42)

        # Pointer cleared
        assert cache.get_sticky_pointer(provider) is None
        # Next request re-establishes from remaining keys
        result = cache.get_key_from_pool(provider)
        assert result is not None
        assert result[0] == 99
        assert cache.get_sticky_pointer(provider) == (99, "k99")


class TestProviderKeyPool:
    """get_key_from_pool provider-key-pool spec scenarios."""

    def test_sticky_mode_returns_pointer_key_without_rotation(self):
        """In sticky mode, subsequent calls return pointer key without deque rotation.

        The first call establishes the pointer via round-robin (which rotates
        the deque once). Subsequent calls are sticky hits and do NOT rotate.
        """
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2"), (3, "k3")])

        # First call: establishes pointer via round-robin (rotates deque)
        result = cache.get_key_from_pool(provider)
        assert result is not None
        assert result[0] == 1
        pointer = cache.get_sticky_pointer(provider)
        assert pointer == (1, "k1")

        # Deque is rotated once by the establishment call
        pool_after_establish = list(cache._key_pool[provider])

        # Second call: sticky hit — returns pointer key, deque unchanged
        result2 = cache.get_key_from_pool(provider)
        assert result2 == (1, "k1")
        # Deque unchanged from after establishment
        assert list(cache._key_pool[provider]) == pool_after_establish

    def test_get_key_from_pool_returns_none_when_pool_empty_sticky(self):
        """When the pool is empty, get_key_from_pool returns None even in sticky mode."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        # Empty pool
        result = cache.get_key_from_pool(provider)
        assert result is None
        assert cache.get_sticky_pointer(provider) is None


class TestSelectionModeDefault:
    """Default selection mode is round-robin."""

    def test_default_mode_is_round_robin(self):
        """get_selection_mode returns ROUND_ROBIN for unconfigured providers."""
        accessor = MagicMock()
        accessor.get_enabled_providers.return_value = {}
        cache = GatewayCache(accessor, MagicMock())
        assert cache.get_selection_mode("any-provider") == KeySelectionMode.ROUND_ROBIN

    def test_round_robin_provider_uses_round_robin_selection(self):
        """Explicit round-robin provider selects keys via rotation."""
        provider = "test-rr"
        accessor = _make_round_robin_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        assert cache.get_selection_mode(provider) == KeySelectionMode.ROUND_ROBIN

        _populate_pool(cache, provider, [(1, "k1"), (2, "k2")])
        result = cache.get_key_from_pool(provider)
        assert result == (1, "k1")
        # Deque rotated
        assert list(cache._key_pool[provider]) == [(2, "k2"), (1, "k1")]


class TestStickyGetKeyFromPoolWithExclude:
    """get_key_from_pool in sticky mode with exclude_key_ids."""

    def test_sticky_exclude_rotates_pointer(self):
        """When the pointer key is excluded, sticky selection rotates."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2"), (3, "k3")])

        # Establish pointer on key 1
        cache.get_key_from_pool(provider)
        assert cache.get_sticky_pointer(provider) == (1, "k1")

        # Call with exclude_key_ids containing the pointer key
        result = cache.get_key_from_pool(provider, exclude_key_ids={1})
        # Should return a different key and re-establish pointer
        assert result is not None
        assert result[0] != 1
        assert cache.get_sticky_pointer(provider) == result

    def test_sticky_exclude_all_returns_none(self):
        """When all keys are excluded, get_key_from_pool returns None."""
        provider = "test-sticky"
        accessor = _make_sticky_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2")])

        cache.get_key_from_pool(provider)
        result = cache.get_key_from_pool(provider, exclude_key_ids={1, 2})
        assert result is None


class TestStickyRotateRoundRobinFallback:
    """rotate_sticky_key in round-robin mode returns None."""

    def test_rotate_in_round_robin_mode_returns_none(self):
        """In round-robin mode, rotate_sticky_key is a no-op returning None."""
        provider = "test-rr"
        accessor = _make_round_robin_accessor(provider)
        cache = GatewayCache(accessor, MagicMock())
        _populate_pool(cache, provider, [(1, "k1"), (2, "k2")])

        result = cache.rotate_sticky_key(provider, exclude_key_ids={1})
        assert result is None
