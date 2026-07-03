"""
Unit tests for src.core.http_client_factory (HttpClientFactory).

Covers test-plan scenarios:
  Section 2: _get_cache_key_for_provider  (always returns provider_name)
  Section 3: get_client_for_provider      (UT-G3-3.1 .. UT-G3-3.6 minus shared)
  Section 4: close_all                    (UT-G3-4.1 .. UT-G3-4.3)
  Section D: ProxyMode simplification verification
  Section E: Pool limits verification
  Section F: HTTP/2 toggle verification
  Section G: Dedicated client isolation (default behaviour)
  Section I: CapacityAwareHttp2Transport injection
  Section K: get_pool_health_summary
  Section L: max_concurrent_streams cap pass-through
  Section M: Per-provider dedicated client (no shared path)
  Security:  SEC-4
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
from src.core.http2.transport import CapacityAwareHttp2Transport
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
    proxy_mode: str = "none",
    static_url: str | None = None,
    max_concurrent_streams_per_connection: int = 5,
) -> ProviderConfig:
    """Create a ProviderConfig with controlled proxy and stream cap.

    Every provider always receives a dedicated HTTP client (keyed by instance
    name); the removed ``dedicated_http_client`` flag is no longer part of the
    schema.
    """
    return ProviderConfig(
        provider_type="openai_like",
        proxy_config=_make_proxy_config(mode=proxy_mode, static_url=static_url),
        max_concurrent_streams_per_connection=max_concurrent_streams_per_connection,
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
            the proxy_config that would come from the provider.
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
# Section 2: _get_cache_key_for_provider (always returns provider_name)
# ==============================================================================


class TestGetCacheKeyForProvider:
    """Tests for HttpClientFactory._get_cache_key_for_provider.

    After the removal of ``dedicated_http_client``, the cache key is always
    the provider instance name — there is no shared/proxy-derived key path.
    """

    def test_returns_provider_name(self) -> None:
        """The cache key is always the provider instance name."""
        provider = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"my_instance": provider})
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("my_instance")
        assert key == "my_instance"

    def test_two_providers_have_different_keys(self) -> None:
        """Two distinct providers produce distinct cache keys."""
        p1 = _make_provider_config(proxy_mode="none")
        p2 = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"instance_a": p1, "instance_b": p2})
        factory = HttpClientFactory(accessor)

        key_a = factory._get_cache_key_for_provider("instance_a")
        key_b = factory._get_cache_key_for_provider("instance_b")
        assert key_a == "instance_a"
        assert key_b == "instance_b"
        assert key_a != key_b

    def test_static_proxy_still_uses_provider_name(self) -> None:
        """A provider with a static proxy still keys on its instance name,
        not the proxy URL (no shared proxy-key path)."""
        url = "http://user:pass@proxy:8080"
        provider = _make_provider_config(proxy_mode="static", static_url=url)
        accessor = _make_accessor_mock(providers={"proxy_prov": provider})
        factory = HttpClientFactory(accessor)

        key = factory._get_cache_key_for_provider("proxy_prov")
        assert key == "proxy_prov"
        assert key != url


# ==============================================================================
# Section 3: get_client_for_provider
# ==============================================================================


class TestGetClientForProvider:
    """Tests for HttpClientFactory.get_client_for_provider."""

    @pytest.mark.asyncio
    async def test_first_request_creates_dedicated_client(self) -> None:
        """UT-G3-3.1: First call for a provider creates a new client."""
        provider = _make_provider_config(proxy_mode="none")
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

    @pytest.mark.asyncio
    async def test_second_request_returns_same_object(self) -> None:
        """UT-G3-3.2: Second call for the same provider returns the cached client."""
        provider = _make_provider_config(proxy_mode="none")
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

    @pytest.mark.asyncio
    async def test_two_dedicated_providers_two_different_clients(self) -> None:
        """UT-G3-3.4: Two providers each get their own client instance."""
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

    @pytest.mark.asyncio
    async def test_unknown_provider_raises_key_error(self) -> None:
        """UT-G3-3.5: Requesting a non-existent provider raises KeyError."""
        accessor = _make_accessor_mock(providers={})
        factory = HttpClientFactory(accessor)

        with pytest.raises(KeyError, match="nonexistent"):
            await factory.get_client_for_provider("nonexistent")

    @pytest.mark.asyncio
    async def test_concurrent_creation_uses_lock(self) -> None:
        """UT-G3-3.6: Two concurrent requests for the same provider create
        only one client."""
        provider = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        creation_count = 0

        def create_client(**kwargs: object) -> MagicMock:
            nonlocal creation_count
            creation_count += 1
            return mock_client

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            client1, client2 = await asyncio.gather(
                factory.get_client_for_provider("shared_prov"),
                factory.get_client_for_provider("shared_prov"),
            )

        assert client1 is client2
        assert client1 is mock_client
        assert creation_count == 1
        assert len(factory._clients) == 1


# ==============================================================================
# Section 4: close_all
# ==============================================================================


class TestCloseAll:
    """Tests for HttpClientFactory.close_all."""

    @pytest.mark.asyncio
    async def test_close_all_closes_all_clients(self) -> None:
        """UT-G3-4.1: close_all calls aclose on every cached client."""
        prov_a = _make_provider_config(proxy_mode="none")
        prov_b = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"prov_a": prov_a, "prov_b": prov_b})
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
            await factory.get_client_for_provider("prov_a")
            await factory.get_client_for_provider("prov_b")

        await factory.close_all()

        mock_a.aclose.assert_called_once()
        mock_b.aclose.assert_called_once()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0

    @pytest.mark.asyncio
    async def test_close_all_empty_cache_no_errors(self) -> None:
        """UT-G3-4.2: Calling close_all when no clients exist does not raise."""
        accessor = _make_accessor_mock(providers={})
        factory = HttpClientFactory(accessor)

        await factory.close_all()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0

    @pytest.mark.asyncio
    async def test_lifecycle_create_close_create_again(self) -> None:
        """UT-G3-4.3: After close_all, a new client can be created for the
        same provider."""
        provider = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client_v1 = MagicMock(spec=httpx.AsyncClient)
        mock_client_v1.aclose = AsyncMock()
        mock_client_v2 = MagicMock(spec=httpx.AsyncClient)
        mock_client_v2.aclose = AsyncMock()

        call_count = 0

        def create_client(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_client_v1
            return mock_client_v2

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            side_effect=create_client,
        ):
            client_v1 = await factory.get_client_for_provider("shared_prov")
            assert client_v1 is mock_client_v1

            await factory.close_all()
            mock_client_v1.aclose.assert_called_once()
            assert len(factory._clients) == 0

            client_v2 = await factory.get_client_for_provider("shared_prov")
            assert client_v2 is mock_client_v2
            assert client_v2 is not client_v1


# ==============================================================================
# Security Tests
# ==============================================================================


class TestSecurity:
    """Security and architectural constraint tests for HttpClientFactory."""

    @pytest.mark.asyncio
    async def test_close_all_no_zombie_connections(self) -> None:
        """SEC-4: After close_all, all clients have aclose() called and the
        internal cache is fully cleared — no zombie connections remain."""
        provider = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"prov": provider})
        factory = HttpClientFactory(accessor)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await factory.get_client_for_provider("prov")

        assert len(factory._clients) == 1

        await factory.close_all()

        mock_client.aclose.assert_called_once()
        assert len(factory._clients) == 0
        assert len(factory._locks) == 0
        assert "prov" not in factory._clients


# ==============================================================================
# Section D: ProxyMode simplification verification
# ==============================================================================


class TestProxyModeSimplification:
    """Tests verifying that STEALTH proxy mode has been fully removed."""

    def test_make_proxy_config_does_not_create_stealth(self) -> None:
        """ProxyConfig(mode='stealth') raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProxyConfig(mode="stealth")

    @pytest.mark.asyncio
    async def test_none_mode_creates_client_with_no_proxy(self) -> None:
        """get_client_for_provider() with ProxyConfig(mode=NONE) ->
        httpx.AsyncClient(proxy=None)."""
        from src.core.constants import ProxyMode

        provider = _make_provider_config(proxy_mode="none")
        assert provider.proxy_config.mode == ProxyMode.NONE
        accessor = _make_accessor_mock(providers={"shared_prov": provider})
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
            await factory.get_client_for_provider("shared_prov")

        assert captured_kwargs.get("proxy") is None

    @pytest.mark.asyncio
    async def test_static_mode_creates_client_with_proxy_url(self) -> None:
        """get_client_for_provider() with ProxyConfig(mode=STATIC,
        static_url='http://p:8080') -> httpx.AsyncClient(proxy='http://p:8080')."""
        from src.core.constants import ProxyMode

        provider = _make_provider_config(
            proxy_mode="static", static_url="http://p:8080"
        )
        assert provider.proxy_config.mode == ProxyMode.STATIC
        accessor = _make_accessor_mock(providers={"proxy_prov": provider})
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
            await factory.get_client_for_provider("proxy_prov")

        assert captured_kwargs.get("proxy") == "http://p:8080"

    def test_source_has_no_stealth_references(self) -> None:
        """The source code contains no STEALTH/stealth/NotImplementedError."""
        import pathlib

        source_path = pathlib.Path("src/core/http_client_factory.py")
        source_text = source_path.read_text()

        assert "STEALTH" not in source_text
        assert '"stealth"' not in source_text
        assert "'stealth'" not in source_text
        assert "NotImplementedError" not in source_text


# ==============================================================================
# Section E: Pool Limits Verification
# ==============================================================================


class TestDefaultPoolLimits:
    """Verify httpx.Limits is created with the default pool configuration."""

    @pytest.mark.asyncio
    async def test_default_pool_limits_applied(self) -> None:
        """Default config creates httpx.Limits with max_connections=100,
        max_keepalive_connections=20, keepalive_expiry=5.0."""
        provider = _make_provider_config(proxy_mode="none")
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
        provider = _make_provider_config(proxy_mode="none")
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
        provider = _make_provider_config(proxy_mode="none")
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
        provider = _make_provider_config(proxy_mode="none")
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
# Section I: CapacityAwareHttp2Transport injection tests
# ==============================================================================


class TestTransportInjection:
    """Verify CapacityAwareHttp2Transport is injected into httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_transport_created_for_http2_client(self) -> None:
        """When http2=True, the client receives CapacityAwareHttp2Transport."""
        provider = _make_provider_config(proxy_mode="none")
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

    @pytest.mark.asyncio
    async def test_transport_config_passed_correctly(self) -> None:
        """Pool config values are correctly forwarded to the transport pool."""
        provider = _make_provider_config(proxy_mode="none")
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
# Section G: Dedicated Client Isolation (every provider is dedicated)
# ==============================================================================


class TestDedicatedClientIsolation:
    """Verify every provider gets an isolated client by default."""

    @pytest.mark.asyncio
    async def test_two_providers_get_isolated_clients(self) -> None:
        """Two providers get separate clients — full connection-pool
        isolation."""
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
# Section K: get_pool_health_summary
# ==============================================================================


class TestGetPoolHealthSummary:
    """Tests for HttpClientFactory.get_pool_health_summary."""

    def test_get_pool_health_summary_all_clients(self) -> None:
        """Returns one entry per cached client with pool health summary dicts."""
        accessor = _make_accessor_mock()
        factory = HttpClientFactory(accessor)

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

        factory._clients = {
            "instance_a": mock_client_a,
            "instance_b": mock_client_b,
        }

        result = factory.get_pool_health_summary()

        assert isinstance(result, dict)
        assert set(result.keys()) == {"instance_a", "instance_b"}
        assert result["instance_a"] == {
            "available": 5,
            "max_connections": 10,
            "active": 3,
        }
        assert result["instance_b"] == {
            "available": 2,
            "max_connections": 8,
            "active": 6,
        }

    def test_get_pool_health_summary_empty_cache(self) -> None:
        """No cached clients -> empty dict."""
        accessor = _make_accessor_mock()
        factory = HttpClientFactory(accessor)

        result = factory.get_pool_health_summary()

        assert result == {}


# ==============================================================================
# Section L: max_concurrent_streams cap pass-through
# ==============================================================================


class TestStreamCapPassThrough:
    """Verify max_concurrent_streams_per_connection flows from ProviderConfig
    through HttpClientFactory into the CapacityAwareHttp2Transport pool."""

    @pytest.mark.asyncio
    async def test_cap_passed_from_provider_config_to_transport(self) -> None:
        """When get_client_for_provider is called, the CapacityAwareHttp2Transport
        receives max_concurrent_streams_cap matching
        provider_config.max_concurrent_streams_per_connection and provider_name
        matching the provider instance name."""
        custom_cap = 7
        provider = _make_provider_config(
            proxy_mode="none",
            max_concurrent_streams_per_connection=custom_cap,
        )
        http_config = HttpClientConfig(http2=True)
        accessor = _make_accessor_mock(
            providers={"cap_prov": provider},
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
            await factory.get_client_for_provider("cap_prov")

        transport = captured_kwargs.get("transport")
        assert isinstance(transport, CapacityAwareHttp2Transport)

        pool = transport._pool
        assert (
            pool._max_concurrent_streams_cap == custom_cap
        ), f"Expected cap={custom_cap}, got {pool._max_concurrent_streams_cap}"
        assert (
            pool._provider_name == "cap_prov"
        ), f"Expected provider_name='cap_prov', got {pool._provider_name}"

    @pytest.mark.asyncio
    async def test_default_cap_is_5(self) -> None:
        """When max_concurrent_streams_per_connection is not overridden, the
        transport pool receives the schema default cap of 5."""
        provider = _make_provider_config(proxy_mode="none")
        http_config = HttpClientConfig(http2=True)
        accessor = _make_accessor_mock(
            providers={"default_prov": provider},
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
            await factory.get_client_for_provider("default_prov")

        transport = captured_kwargs.get("transport")
        assert isinstance(transport, CapacityAwareHttp2Transport)
        assert transport._pool._max_concurrent_streams_cap == 5
        assert transport._pool._provider_name == "default_prov"


# ==============================================================================
# Section M: Per-provider dedicated client (no shared path)
# ==============================================================================


class TestPerProviderDedicatedClient:
    """Verify every provider always gets a dedicated client and that no
    shared-client code path remains."""

    @pytest.mark.asyncio
    async def test_provider_always_gets_dedicated_client(self) -> None:
        """A single provider always gets a dedicated client keyed by its own
        instance name — never a shared '__none__' or proxy-URL key."""
        provider = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"solo": provider})
        factory = HttpClientFactory(accessor)

        assert factory._get_cache_key_for_provider("solo") == "solo"

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        with patch(
            "src.core.http_client_factory.httpx.AsyncClient",
            return_value=mock_client,
        ):
            client = await factory.get_client_for_provider("solo")

        assert client is mock_client
        assert "solo" in factory._clients
        assert len(factory._clients) == 1

    @pytest.mark.asyncio
    async def test_no_shared_client_path(self) -> None:
        """Two providers with identical 'none' proxy configs (which previously
        shared a '__none__' cache key) now get separate clients — confirming
        no shared-client code path remains."""
        p1 = _make_provider_config(proxy_mode="none")
        p2 = _make_provider_config(proxy_mode="none")
        accessor = _make_accessor_mock(providers={"alpha": p1, "beta": p2})
        factory = HttpClientFactory(accessor)

        # The proxy-based cache-key method was removed entirely.
        assert not hasattr(factory, "_get_cache_key_for_proxy")

        # Both providers get distinct keys (their own names).
        assert factory._get_cache_key_for_provider("alpha") == "alpha"
        assert factory._get_cache_key_for_provider("beta") == "beta"

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
            client_a = await factory.get_client_for_provider("alpha")
            client_b = await factory.get_client_for_provider("beta")

        assert client_a is mock_a
        assert client_b is mock_b
        assert client_a is not client_b
        assert "alpha" in factory._clients
        assert "beta" in factory._clients
        assert len(factory._clients) == 2
