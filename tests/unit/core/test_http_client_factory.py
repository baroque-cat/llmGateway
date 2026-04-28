"""
Unit tests for src.core.http_client_factory (HttpClientFactory).

Covers test-plan scenarios:
  Section 2: _get_cache_key_for_provider  (UT-G3-2.1 .. UT-G3-2.5)
  Section 3: get_client_for_provider      (UT-G3-3.1 .. UT-G3-3.6)
  Section 4: close_all                    (UT-G3-4.1 .. UT-G3-4.3)
  Security:  SEC-1, SEC-2, SEC-4
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import ProviderConfig, ProxyConfig
from src.core.http_client_factory import HttpClientFactory

# ==============================================================================
# Helpers
# ==============================================================================


def _make_proxy_config(
    mode: str = "none", static_url: str | None = None
) -> ProxyConfig:
    """Create a ProxyConfig. For 'static' mode, static_url is required."""
    if mode == "static":
        return ProxyConfig(mode="static", static_url=static_url or "http://proxy:8080")
    return ProxyConfig(mode=mode)


def _make_provider_config(
    dedicated: bool = False,
    proxy_mode: str = "none",
    static_url: str | None = None,
) -> ProviderConfig:
    """Create a ProviderConfig with controlled dedicated_http_client and proxy."""
    return ProviderConfig(
        provider_type="mock",
        keys_path="keys/mock/",
        dedicated_http_client=dedicated,
        proxy_config=_make_proxy_config(mode=proxy_mode, static_url=static_url),
    )


def _make_accessor_mock(
    providers: dict[str, ProviderConfig] | None = None,
    proxy_configs: dict[str, ProxyConfig] | None = None,
) -> MagicMock:
    """Create a mock ConfigAccessor.

    Args:
        providers: Maps provider_name -> ProviderConfig. If None, empty dict.
        proxy_configs: Maps provider_name -> ProxyConfig. If provided, overrides
            the proxy_config that would come from the provider. This allows
            testing fallback scenarios where get_provider returns None but
            get_proxy_config returns a valid config.
    """
    accessor = MagicMock()
    providers = providers or {}
    proxy_configs = proxy_configs or {}

    def get_provider(name: str) -> ProviderConfig | None:
        return providers.get(name)

    def get_proxy_config(name: str) -> ProxyConfig | None:
        if name in proxy_configs:
            return proxy_configs[name]
        provider = providers.get(name)
        return provider.proxy_config if provider else None

    accessor.get_provider = MagicMock(side_effect=get_provider)
    accessor.get_proxy_config = MagicMock(side_effect=get_proxy_config)
    return accessor


# ==============================================================================
# Section 2: _get_cache_key_for_provider
# ==============================================================================


class TestGetCacheKeyForProvider:
    """Tests for HttpClientFactory._get_cache_key_for_provider."""

    # --- UT-G3-2.1: dedicated_http_client=True -> key = instance name ---
    def test_dedicated_returns_instance_name(self) -> None:
        """UT-G3-2.1: When dedicated_http_client=True, the cache key is the provider name."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"my_instance": provider})
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("my_instance")
        assert key == "my_instance"

    # --- UT-G3-2.2: dedicated_http_client=False + mode="none" -> key = "__none__" ---
    def test_shared_none_mode_returns_none_key(self) -> None:
        """UT-G3-2.2: Non-dedicated provider with proxy mode 'none' gets '__none__' key."""
        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("shared_prov")
        assert key == "__none__"

    # --- UT-G3-2.3: dedicated_http_client=False + mode="static" -> key = static_url ---
    def test_shared_static_mode_returns_url_key(self) -> None:
        """UT-G3-2.3: Non-dedicated provider with static proxy gets URL as key."""
        url = "http://user:pass@proxy:8080"
        provider = _make_provider_config(
            dedicated=False, proxy_mode="static", static_url=url
        )
        accessor = _make_accessor_mock(providers={"proxy_prov": provider})
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("proxy_prov")
        assert key == url

    # --- UT-G3-2.4: Provider not found -> fallback to proxy key ---
    def test_missing_provider_falls_back_to_proxy_key(self) -> None:
        """UT-G3-2.4: When get_provider returns None, falls back to proxy-based key."""
        proxy_cfg = _make_proxy_config(mode="none")
        # Provider not found in get_provider, but proxy config is available
        accessor = _make_accessor_mock(
            providers={},  # No providers -> get_provider returns None
            proxy_configs={"unknown_prov": proxy_cfg},  # But proxy config exists
        )
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("unknown_prov")
        assert key == "__none__"

    # --- UT-G3-2.5: Two dedicated providers -> two different keys (no collision) ---
    def test_two_dedicated_providers_have_different_keys(self) -> None:
        """UT-G3-2.5: Two dedicated providers produce distinct cache keys."""
        p1 = _make_provider_config(dedicated=True, proxy_mode="none")
        p2 = _make_provider_config(dedicated=True, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"instance_a": p1, "instance_b": p2})
        factory = HttpClientFactory(accessor)

        key_a = factory._get_cache_key_for_provider("instance_a")
        key_b = factory._get_cache_key_for_provider("instance_b")
        assert key_a == "instance_a"
        assert key_b == "instance_b"
        assert key_a != key_b


# ==============================================================================
# Section 3: get_client_for_provider
# ==============================================================================


class TestGetClientForProvider:
    """Tests for HttpClientFactory.get_client_for_provider."""

    # --- UT-G3-3.1: First request creates dedicated client ---
    @pytest.mark.asyncio
    async def test_first_request_creates_dedicated_client(self) -> None:
        """UT-G3-3.1: First call for a dedicated provider creates a new client."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"dedicated_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()
        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            client = await factory.get_client_for_provider("dedicated_prov")

        assert client is mock_client
        assert "dedicated_prov" in factory._clients

    # --- UT-G3-3.2: Second request returns same object ---
    @pytest.mark.asyncio
    async def test_second_request_returns_same_object(self) -> None:
        """UT-G3-3.2: Second call for the same provider returns the cached client."""
        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()
        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            client1 = await factory.get_client_for_provider("shared_prov")
            client2 = await factory.get_client_for_provider("shared_prov")

        assert client1 is client2
        assert client1 is mock_client

    # --- UT-G3-3.3: Dedicated client isolated from shared ---
    @pytest.mark.asyncio
    async def test_dedicated_client_isolated_from_shared(self) -> None:
        """UT-G3-3.3: A dedicated client has a different object from the shared client."""
        dedicated_prov = _make_provider_config(dedicated=True, proxy_mode="none")
        shared_prov = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(
            providers={"dedicated_prov": dedicated_prov, "shared_prov": shared_prov}
        )
        factory = HttpClientFactory(accessor)

        mock_client_dedicated = MagicMock(spec=httpx.AsyncClient)
        mock_client_dedicated.aclose = AsyncMock()
        mock_client_shared = MagicMock(spec=httpx.AsyncClient)
        mock_client_shared.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_client_dedicated
            return mock_client_shared

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            client_d = await factory.get_client_for_provider("dedicated_prov")
            client_s = await factory.get_client_for_provider("shared_prov")

        assert client_d is mock_client_dedicated
        assert client_s is mock_client_shared
        assert client_d is not client_s

    # --- UT-G3-3.4: Two dedicated providers -> two different clients ---
    @pytest.mark.asyncio
    async def test_two_dedicated_providers_two_different_clients(self) -> None:
        """UT-G3-3.4: Two dedicated providers each get their own client instance."""
        p1 = _make_provider_config(dedicated=True, proxy_mode="none")
        p2 = _make_provider_config(dedicated=True, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"instance_a": p1, "instance_b": p2})
        factory = HttpClientFactory(accessor)

        mock_a = MagicMock(spec=httpx.AsyncClient)
        mock_a.aclose = AsyncMock()
        mock_b = MagicMock(spec=httpx.AsyncClient)
        mock_b.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_a
            return mock_b

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            client_a = await factory.get_client_for_provider("instance_a")
            client_b = await factory.get_client_for_provider("instance_b")

        assert client_a is mock_a
        assert client_b is mock_b
        assert client_a is not client_b
        assert len(factory._clients) == 2

    # --- UT-G3-3.5: KeyError for unknown provider ---
    @pytest.mark.asyncio
    async def test_unknown_provider_raises_key_error(self) -> None:
        """UT-G3-3.5: Requesting a non-existent provider raises KeyError."""
        accessor = _make_accessor_mock(providers={})
        factory = HttpClientFactory(accessor)

        with pytest.raises(KeyError, match="nonexistent"):
            await factory.get_client_for_provider("nonexistent")

    # --- UT-G3-3.6: Concurrent creation (lock) - race condition ---
    @pytest.mark.asyncio
    async def test_concurrent_creation_uses_lock(self) -> None:
        """UT-G3-3.6: Two concurrent requests for the same provider create only one client."""
        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        creation_count = 0

        def create_client(**kwargs):
            nonlocal creation_count
            creation_count += 1
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            # Run two concurrent requests
            client1, client2 = await asyncio.gather(
                factory.get_client_for_provider("shared_prov"),
                factory.get_client_for_provider("shared_prov"),
            )

        assert client1 is client2
        assert client1 is mock_client
        # Only one client should have been created despite two concurrent calls
        assert creation_count == 1
        assert len(factory._clients) == 1


# ==============================================================================
# Section 4: close_all
# ==============================================================================


class TestCloseAll:
    """Tests for HttpClientFactory.close_all."""

    # --- UT-G3-4.1: close_all closes all clients, including dedicated ---
    @pytest.mark.asyncio
    async def test_close_all_closes_all_clients(self) -> None:
        """UT-G3-4.1: close_all calls aclose on every cached client."""
        dedicated_prov = _make_provider_config(dedicated=True, proxy_mode="none")
        shared_prov = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(
            providers={"dedicated_prov": dedicated_prov, "shared_prov": shared_prov}
        )
        factory = HttpClientFactory(accessor)

        mock_dedicated = MagicMock(spec=httpx.AsyncClient)
        mock_dedicated.aclose = AsyncMock()
        mock_shared = MagicMock(spec=httpx.AsyncClient)
        mock_shared.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_dedicated
            return mock_shared

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            await factory.get_client_for_provider("dedicated_prov")
            await factory.get_client_for_provider("shared_prov")

        await factory.close_all()

        mock_dedicated.aclose.assert_called_once()
        mock_shared.aclose.assert_called_once()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0

    # --- UT-G3-4.2: close_all with empty cache - no errors ---
    @pytest.mark.asyncio
    async def test_close_all_empty_cache_no_errors(self) -> None:
        """UT-G3-4.2: Calling close_all when no clients exist does not raise."""
        accessor = _make_accessor_mock(providers={})
        factory = HttpClientFactory(accessor)

        # No clients created - close_all should succeed without errors
        await factory.close_all()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0

    # --- UT-G3-4.3: Lifecycle: create -> use -> close_all -> create again ---
    @pytest.mark.asyncio
    async def test_lifecycle_create_close_create_again(self) -> None:
        """UT-G3-4.3: After close_all, a new client can be created for the same provider."""
        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client_v1 = MagicMock(spec=httpx.AsyncClient)
        mock_client_v1.aclose = AsyncMock()
        mock_client_v2 = MagicMock(spec=httpx.AsyncClient)
        mock_client_v2.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_client_v1
            return mock_client_v2

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            # Phase 1: Create
            client_v1 = await factory.get_client_for_provider("shared_prov")
            assert client_v1 is mock_client_v1

            # Phase 2: Close all
            await factory.close_all()
            mock_client_v1.aclose.assert_called_once()
            assert len(factory._clients) == 0

            # Phase 3: Create again - should get a new client
            client_v2 = await factory.get_client_for_provider("shared_prov")
            assert client_v2 is mock_client_v2
            assert client_v2 is not client_v1


# ==============================================================================
# Security Tests
# ==============================================================================


class TestSecurity:
    """Security and architectural constraint tests for HttpClientFactory."""

    # --- SEC-1: dedicated_http_client does not bypass proxy isolation ---
    @pytest.mark.asyncio
    async def test_dedicated_does_not_bypass_proxy_isolation(self) -> None:
        """SEC-1: A dedicated client with a static proxy uses its own key
        (provider name), not the shared proxy key. The dedicated flag isolates
        the client regardless of proxy configuration."""
        # Provider with dedicated=True AND static proxy
        dedicated_with_proxy = _make_provider_config(
            dedicated=True, proxy_mode="static", static_url="http://proxy:8080"
        )
        # Another non-dedicated provider with the same static proxy
        shared_with_proxy = _make_provider_config(
            dedicated=False, proxy_mode="static", static_url="http://proxy:8080"
        )
        accessor = _make_accessor_mock(
            providers={
                "dedicated_proxy": dedicated_with_proxy,
                "shared_proxy": shared_with_proxy,
            }
        )
        factory = HttpClientFactory(accessor)

        # The dedicated provider's key should be its name, NOT the proxy URL
        key_dedicated = factory._get_cache_key_for_provider("dedicated_proxy")
        key_shared = factory._get_cache_key_for_provider("shared_proxy")

        assert key_dedicated == "dedicated_proxy"
        assert key_shared == "http://proxy:8080"
        assert key_dedicated != key_shared

    # --- SEC-2: Instance name collision with proxy key ---
    def test_instance_name_collision_with_proxy_key(self) -> None:
        """SEC-2: If a provider is named '__none__', its dedicated key collides
        with the shared proxy key '__none__'. This demonstrates a known naming
        collision vulnerability - provider names matching proxy-derived keys
        ('__none__', URLs) break dedicated client isolation."""
        # Provider named "__none__" with dedicated=True
        collision_provider = _make_provider_config(dedicated=True, proxy_mode="none")
        # Regular shared provider with proxy mode "none"
        shared_provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(
            providers={
                "__none__": collision_provider,
                "regular": shared_provider,
            }
        )
        factory = HttpClientFactory(accessor)

        key_collision = factory._get_cache_key_for_provider("__none__")
        key_shared = factory._get_cache_key_for_provider("regular")

        # Both keys are "__none__" - this IS a collision!
        # The dedicated provider's isolation is broken because its name
        # matches the proxy-derived key.
        assert key_collision == "__none__"
        assert key_shared == "__none__"
        # Collision confirmed - this is a vulnerability in the current design:
        # provider names should be restricted from matching proxy-derived keys.
        assert key_collision == key_shared

    # --- SEC-4: close_all does not leave zombie TCP connections ---
    @pytest.mark.asyncio
    async def test_close_all_no_zombie_connections(self) -> None:
        """SEC-4: After close_all, all clients have aclose() called and
        the internal cache is fully cleared - no zombie connections remain."""
        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await factory.get_client_for_provider("prov")

        # Verify client is cached
        assert len(factory._clients) == 1

        await factory.close_all()

        # After close_all: cache is empty, aclose was called, no references remain
        mock_client.aclose.assert_called_once()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0
        # No dangling references - the client object is not referenced by the factory
        assert "__none__" not in factory._clients
