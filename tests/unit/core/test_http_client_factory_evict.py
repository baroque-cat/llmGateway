#!/usr/bin/env python3

"""Tests for HttpClientFactory.evict() and close_all() — P1 transport eviction.

Verifies that:
  - evict(provider) removes the cached client
  - Next get_client_for_provider() creates a new one
  - The old client is retired and closed after the grace period
  - close_all() closes both active and retired clients
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.http_client_factory import HttpClientFactory


@pytest.fixture
def mock_accessor() -> MagicMock:
    """Create a mock ConfigAccessor."""
    accessor = MagicMock()
    http_config = MagicMock()
    http_config.http2 = False
    http_config.pool = MagicMock()
    http_config.pool.max_connections = 100
    http_config.pool.max_keepalive_connections = 20
    http_config.pool_health_log_interval_sec = 300
    accessor.get_http_client_config.return_value = http_config
    return accessor


@pytest.fixture
def factory(mock_accessor: MagicMock) -> HttpClientFactory:
    """Create an HttpClientFactory instance."""
    return HttpClientFactory(mock_accessor)


# ---------------------------------------------------------------------------
# Test evict() removes cached client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_removes_cached_client(factory: HttpClientFactory) -> None:
    """evict() removes the client from the active cache."""
    provider_name = "test_provider"

    # Create and cache a client
    client1 = await factory.get_client_for_provider(provider_name)
    assert provider_name in factory._clients
    assert factory._clients[provider_name] is client1

    # Evict the client
    await factory.evict(provider_name)

    # Verify it's removed from active cache
    assert provider_name not in factory._clients

    # Verify it's in retired set
    assert client1 in factory._retired_clients


# ---------------------------------------------------------------------------
# Test next get_client_for_provider() creates a new client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_creates_new_client_on_next_get(
    factory: HttpClientFactory,
) -> None:
    """After evict(), the next get_client_for_provider() creates a new client."""
    provider_name = "test_provider"

    # Create first client
    client1 = await factory.get_client_for_provider(provider_name)

    # Evict it
    await factory.evict(provider_name)

    # Get a new client
    client2 = await factory.get_client_for_provider(provider_name)

    # Verify it's a different client
    assert client2 is not client1
    assert provider_name in factory._clients
    assert factory._clients[provider_name] is client2


# ---------------------------------------------------------------------------
# Test retired client is closed after grace period
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retired_client_closed_after_grace_period(
    factory: HttpClientFactory,
) -> None:
    """The retired client is closed after the grace period."""
    provider_name = "test_provider"

    # Create and cache a client
    client = await factory.get_client_for_provider(provider_name)
    client.aclose = AsyncMock()

    # Evict the client
    await factory.evict(provider_name)

    # Verify it's in retired set
    assert client in factory._retired_clients

    # Patch the grace period to 0 for testing
    with patch("src.core.http_client_factory._RETIRED_CLIENT_GRACE_SEC", 0):
        # Wait for the background task to complete
        await asyncio.sleep(0.1)

    # Verify aclose was called
    client.aclose.assert_awaited_once()

    # Verify it's removed from retired set
    assert client not in factory._retired_clients


# ---------------------------------------------------------------------------
# Test close_all() closes both active and retired clients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all_closes_active_and_retired(
    factory: HttpClientFactory,
) -> None:
    """close_all() closes both active and retired clients."""
    # Create two active clients
    client1 = await factory.get_client_for_provider("provider1")
    client2 = await factory.get_client_for_provider("provider2")
    client1.aclose = AsyncMock()
    client2.aclose = AsyncMock()

    # Evict one to create a retired client
    await factory.evict("provider1")
    assert client1 in factory._retired_clients
    assert "provider2" in factory._clients

    # Close all
    await factory.close_all()

    # Verify both clients were closed
    client1.aclose.assert_awaited_once()
    client2.aclose.assert_awaited_once()

    # Verify caches are cleared
    assert len(factory._clients) == 0
    assert len(factory._retired_clients) == 0


# ---------------------------------------------------------------------------
# Test evict() on non-existent provider is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_nonexistent_provider_is_noop(
    factory: HttpClientFactory,
) -> None:
    """evict() on a provider that doesn't exist is a no-op."""
    # Should not raise
    await factory.evict("nonexistent_provider")

    # Verify no state changes
    assert len(factory._clients) == 0
    assert len(factory._retired_clients) == 0
