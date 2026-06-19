"""httpx-compatible transport wrapping the capacity-aware HTTP/2 pool.

Provides :class:`CapacityAwareHttp2Transport` — a subclass of
:class:`httpx.AsyncHTTPTransport` that uses
:class:`~src.core.http2.pool.CapacityAwareHttp2Pool` as its
internal connection pool.

This is the public entry point — imported by :class:`HttpClientFactory`
and passed as ``transport=`` to ``httpx.AsyncClient``.
"""

from __future__ import annotations

import typing

import httpx

from src.core.http2.pool import CapacityAwareHttp2Pool

__all__ = ["CapacityAwareHttp2Transport"]

# Resolve httpx private types at module level to avoid pyright
# `reportPrivateUsage` errors in type annotations.
type _VerifyTypes = typing.Any  # ssl.SSLContext | str | bool
type _CertTypes = typing.Any  # path / tuple / list
type _ProxyTypes = typing.Any  # str | httpx.URL | httpx.Proxy


class CapacityAwareHttp2Transport(httpx.AsyncHTTPTransport):
    """httpx transport with capacity-aware HTTP/2 connection pool.

    Subclasses :class:`httpx.AsyncHTTPTransport` and replaces its
    default ``httpcore.AsyncConnectionPool`` with
    :class:`~src.core.http2.pool.CapacityAwareHttp2Pool`, which
    implements the full PR #1088 mechanics (connection_request_count,
    on_capacity_update callback, capacity-aware routing).

    All request/response conversion (``httpx.Request`` →
    ``httpcore.Request`` → ``httpcore.Response`` →
    ``httpx.Response``) is handled by the parent class.
    """

    def __init__(
        self,
        verify: _VerifyTypes = True,
        cert: _CertTypes | None = None,
        trust_env: bool = True,
        http1: bool = True,
        http2: bool = False,
        limits: httpx.Limits = httpx._config.DEFAULT_LIMITS,  # type: ignore[reportPrivateUsage]
        proxy: _ProxyTypes | None = None,
        uds: str | None = None,
        local_address: str | None = None,
        retries: int = 0,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> None:
        ssl_context = httpx.create_ssl_context(
            verify=verify, cert=cert, trust_env=trust_env
        )

        if proxy is None:
            self._pool = CapacityAwareHttp2Pool(
                ssl_context=ssl_context,
                max_connections=limits.max_connections,
                max_keepalive_connections=limits.max_keepalive_connections,
                keepalive_expiry=limits.keepalive_expiry,
                http1=http1,
                http2=http2,
                uds=uds,
                local_address=local_address,
                retries=retries,
                socket_options=socket_options,
            )
        else:
            raise ValueError(
                "CapacityAwareHttp2Transport does not support proxy "
                "configurations. Use the project's built-in proxy support "
                "via HttpClientFactory instead."
            )
