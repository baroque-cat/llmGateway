"""
Unit tests for src.core.http_client_factory (HttpClientFactory).

Covers test-plan scenarios:
  Section 2: _get_cache_key_for_provider  (UT-G3-2.1 .. UT-G3-2.5)
  Section 3: get_client_for_provider      (UT-G3-3.1 .. UT-G3-3.6)
  Section 4: close_all                    (UT-G3-4.1 .. UT-G3-4.3)
  Section D: ProxyMode simplification verification
  Security:  SEC-1, SEC-2, SEC-4
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import (
    HttpClientConfig,
    HttpClientPoolConfig,
    ProviderConfig,
    ProxyConfig,
)
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
    dedicated: bool = True,
    proxy_mode: str = "none",
    static_url: str | None = None,
) -> ProviderConfig:
    """Create a ProviderConfig with controlled dedicated_http_client and proxy."""
    return ProviderConfig(
        provider_type="openai_like",
        dedicated_http_client=dedicated,
        proxy_config=_make_proxy_config(mode=proxy_mode, static_url=static_url),
    )


def _make_accessor_mock(
    providers: dict[str, ProviderConfig] | None = None,
    proxy_configs: dict[str, ProxyConfig] | None = None,
    http_client_config: HttpClientConfig | None = None,
) -> MagicMock:
    """Create a mock ConfigAccessor.

    Args:
        providers: Maps provider_name -> ProviderConfig. If None, empty dict.
        proxy_configs: Maps provider_name -> ProxyConfig. If provided, overrides
            the proxy_config that would come from the provider. This allows
            testing fallback scenarios where get_provider returns None but
            get_proxy_config returns a valid config.
        http_client_config: Overrides the response of get_http_client_config().
            If None, returns a default HttpClientConfig().
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
    accessor.get_http_client_config = MagicMock(
        return_value=http_client_config or HttpClientConfig()
    )
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


# ==============================================================================
# Section D: ProxyMode simplification verification
# ==============================================================================


class TestProxyModeSimplification:
    """
    Tests verifying that STEALTH proxy mode has been fully removed from
    HttpClientFactory and that only NONE and STATIC modes are supported.
    """

    def test_make_proxy_config_does_not_create_stealth(self) -> None:
        """
        _make_proxy_config does not create ProxyConfig(mode="stealth").
        Attempting to create ProxyConfig(mode="stealth") raises ValidationError.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProxyConfig(mode="stealth")

    @pytest.mark.asyncio
    async def test_none_mode_creates_client_with_no_proxy(self) -> None:
        """
        get_client_for_provider() with ProxyConfig(mode=NONE) →
        httpx.AsyncClient(proxy=None)
        """
        from src.core.constants import ProxyMode

        provider = _make_provider_config(dedicated=False, proxy_mode="none")
        assert provider.proxy_config.mode == ProxyMode.NONE
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict = {}

        def capture_client(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("shared_prov")

        assert captured_kwargs.get("proxy") is None

    @pytest.mark.asyncio
    async def test_static_mode_creates_client_with_proxy_url(self) -> None:
        """
        get_client_for_provider() with ProxyConfig(mode=STATIC, static_url="http://p:8080") →
        httpx.AsyncClient(proxy="http://p:8080")
        """
        from src.core.constants import ProxyMode

        provider = _make_provider_config(
            dedicated=False, proxy_mode="static", static_url="http://p:8080"
        )
        assert provider.proxy_config.mode == ProxyMode.STATIC
        accessor = _make_accessor_mock(providers={"proxy_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict = {}

        def capture_client(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("proxy_prov")

        assert captured_kwargs.get("proxy") == "http://p:8080"

    def test_source_has_no_stealth_references(self) -> None:
        """
        grep for STEALTH, "stealth", NotImplementedError in http_client_factory.py →
        no matches. Verifies the source code has been fully cleaned.
        """
        import pathlib

        source_path = pathlib.Path("src/core/http_client_factory.py")
        source_text = source_path.read_text()

        assert (
            "STEALTH" not in source_text
        ), "http_client_factory.py should not contain 'STEALTH'"
        assert (
            '"stealth"' not in source_text
        ), "http_client_factory.py should not contain '\"stealth\"'"
        assert (
            "'stealth'" not in source_text
        ), "http_client_factory.py should not contain \"'stealth'\""
        assert (
            "NotImplementedError" not in source_text
        ), "http_client_factory.py should not contain 'NotImplementedError'"


# ==============================================================================
# Section E: Pool Limits Verification
# ==============================================================================


class TestDefaultPoolLimits:
    """Verify httpx.Limits is created with the default pool configuration."""

    @pytest.mark.asyncio
    async def test_default_pool_limits_applied(self) -> None:
        """Default config creates httpx.Limits with max_connections=100,
        max_keepalive_connections=20, keepalive_expiry=5.0."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"test_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        limits = captured_kwargs["limits"]
        assert isinstance(limits, httpx.Limits)
        assert limits.max_connections == 100
        assert limits.max_keepalive_connections == 20
        assert limits.keepalive_expiry == 5.0


class TestCustomPoolLimits:
    """Verify custom pool limits from config are passed to httpx.Limits."""

    @pytest.mark.asyncio
    async def test_custom_pool_limits_applied(self) -> None:
        """Custom HttpClientPoolConfig values are used when creating httpx.Limits."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        custom_pool = HttpClientPoolConfig(
            max_connections=50,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )
        custom_http = HttpClientConfig(pool=custom_pool)
        accessor = _make_accessor_mock(
            providers={"test_prov": provider},
            http_client_config=custom_http,
        )
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        limits = captured_kwargs["limits"]
        assert isinstance(limits, httpx.Limits)
        assert limits.max_connections == 50
        assert limits.max_keepalive_connections == 10
        assert limits.keepalive_expiry == 30.0


# ==============================================================================
# Section F: HTTP/2 Toggle Verification
# ==============================================================================


class TestHttp2Toggle:
    """Verify http2 is enabled or disabled per HttpClientConfig."""

    @pytest.mark.asyncio
    async def test_http2_enabled(self) -> None:
        """http2=True in config creates client with http2=True."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        http_config = HttpClientConfig(http2=True)
        accessor = _make_accessor_mock(
            providers={"test_prov": provider},
            http_client_config=http_config,
        )
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        assert captured_kwargs["http2"] is True

    @pytest.mark.asyncio
    async def test_http2_disabled(self) -> None:
        """http2=False in config creates client with http2=False."""
        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        http_config = HttpClientConfig(http2=False)
        accessor = _make_accessor_mock(
            providers={"test_prov": provider},
            http_client_config=http_config,
        )
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        assert captured_kwargs["http2"] is False


# ==============================================================================
# Section I: CapacityAwareHttp2Transport injection tests (HTTP/2 refactor)
# ==============================================================================


class TestTransportInjection:
    """Verify CapacityAwareHttp2Transport is injected into httpx.AsyncClient."""

    # --- Task 1, test 1: transport created for http2 clients ---
    @pytest.mark.asyncio
    async def test_transport_created_for_http2_client(self) -> None:
        """When http2=True, the client receives CapacityAwareHttp2Transport as transport."""
        from src.core.http2.transport import CapacityAwareHttp2Transport

        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        http_config = HttpClientConfig(http2=True)
        accessor = _make_accessor_mock(
            providers={"test_prov": provider},
            http_client_config=http_config,
        )
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        transport = captured_kwargs.get("transport")
        assert transport is not None, "transport kwarg must be present"
        assert isinstance(
            transport, CapacityAwareHttp2Transport
        ), f"Expected CapacityAwareHttp2Transport, got {type(transport)}"
        assert captured_kwargs.get("http2") is True

    # --- Task 1, test 2: transport config passed correctly ---
    @pytest.mark.asyncio
    async def test_transport_config_passed_correctly(self) -> None:
        """Pool config values are correctly forwarded to the transport constructor."""
        from src.core.http2.transport import CapacityAwareHttp2Transport

        provider = _make_provider_config(dedicated=True, proxy_mode="none")
        custom_pool = HttpClientPoolConfig(
            max_connections=42,
            max_keepalive_connections=7,
            keepalive_expiry=30.0,
        )
        http_config = HttpClientConfig(http2=True, pool=custom_pool)
        accessor = _make_accessor_mock(
            providers={"test_prov": provider},
            http_client_config=http_config,
        )
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        captured_kwargs: dict[str, object] = {}

        def capture_client(**kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=capture_client,
        ):
            await factory.get_client_for_provider("test_prov")

        transport = captured_kwargs.get("transport")
        assert isinstance(transport, CapacityAwareHttp2Transport)

        # Verify pool config values are correctly forwarded to the inner pool
        pool = transport._pool
        assert (
            pool._max_connections == 42
        ), f"Expected max_connections=42, got {pool._max_connections}"
        assert pool._max_keepalive_connections == 7, (
            f"Expected max_keepalive_connections=7, "
            f"got {pool._max_keepalive_connections}"
        )
        assert (
            pool._keepalive_expiry == 30.0
        ), f"Expected keepalive_expiry=30.0, got {pool._keepalive_expiry}"


# ==============================================================================
# Section G: Dedicated Client Isolation (Default = True)
# ==============================================================================


class TestDedicatedClientIsolation:
    """Verify dedicated_http_client=True (new default) isolates clients per provider."""

    @pytest.mark.asyncio
    async def test_new_default_dedicated_creates_isolated_clients(self) -> None:
        """Two providers with dedicated_http_client=True (default) get separate clients."""
        p1 = _make_provider_config(proxy_mode="none")
        p2 = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"instance_a": p1, "instance_b": p2})
        factory = HttpClientFactory(accessor)

        mock_a = MagicMock(spec=httpx.AsyncClient)
        mock_a.aclose = AsyncMock()
        mock_b = MagicMock(spec=httpx.AsyncClient)
        mock_b.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs: object) -> MagicMock:
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


# ==============================================================================
# Section K: get_pool_health_summary (pool health factory)
# ==============================================================================


class TestGetPoolHealthSummary:
    """Tests for HttpClientFactory.get_pool_health_summary."""

    def test_get_pool_health_summary_all_clients(self) -> None:
        """When get_pool_health_summary() is called with cached clients,
        returns one entry per client with their pool health summary dicts.
        """
        accessor = _make_accessor_mock()
        factory = HttpClientFactory(accessor)

        # Build mock client A with transport → pool → get_health_summary chain
        mock_client_a = MagicMock()
        mock_pool_a = MagicMock()
        mock_pool_a.get_health_summary.return_value = {
            "available": 5,
            "max_connections": 10,
            "active": 3,
        }
        mock_transport_a = MagicMock()
        mock_transport_a._pool = mock_pool_a
        mock_client_a._transport = mock_transport_a

        # Build mock client B with transport → pool → get_health_summary chain
        mock_client_b = MagicMock()
        mock_pool_b = MagicMock()
        mock_pool_b.get_health_summary.return_value = {
            "available": 2,
            "max_connections": 8,
            "active": 6,
        }
        mock_transport_b = MagicMock()
        mock_transport_b._pool = mock_pool_b
        mock_client_b._transport = mock_transport_b

        # Populate the internal clients cache directly
        factory._clients = {
            "instance_a": mock_client_a,
            "instance_b": mock_client_b,
        }

        result = factory.get_pool_health_summary()

        assert isinstance(result, dict)
        assert set(result.keys()) == {"instance_a", "instance_b"}
        assert result["instance_a"] == {"available": 5, "max_connections": 10, "active": 3}
        assert result["instance_b"] == {"available": 2, "max_connections": 8, "active": 6}

    def test_get_pool_health_summary_empty_cache(self) -> None:
        """When get_pool_health_summary() is called and no clients are cached,
        an empty dict is returned.
        """
        accessor = _make_accessor_mock()
        factory = HttpClientFactory(accessor)

        # No clients have been added — _clients is an empty dict
        result = factory.get_pool_health_summary()

        assert result == {}


# ==============================================================================
# Section H: Shared Client Pooling (dedicated_http_client=False)
# ==============================================================================


class TestSharedClientPooling:
    """Verify dedicated_http_client=False shares clients across providers."""

    @pytest.mark.asyncio
    async def test_two_shared_clients_share_same_object(self) -> None:
        """Two providers with dedicated_http_client=False share the same client."""
        p1 = _make_provider_config(dedicated=False, proxy_mode="none")
        p2 = _make_provider_config(dedicated=False, proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_a": p1, "shared_b": p2})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            client_a = await factory.get_client_for_provider("shared_a")
            client_b = await factory.get_client_for_provider("shared_b")

        assert client_a is mock_client
        assert client_b is mock_client
        assert client_a is client_b
        assert len(factory._clients) == 1
