"""Shared fixtures for connection pool stress tests.

Provides factory fixtures for :class:`EphemeralHttp2Server` and
:class:`MetricsCollector` so that each test can create a server with
customised parameters without duplicating lifecycle boilerplate.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
import pytest_asyncio

from tests.stress.ephemeral_api import EphemeralHttp2Server
from tests.stress.metrics import MetricsCollector


@pytest_asyncio.fixture(scope="session")
async def http2_server_factory() -> AsyncGenerator[Callable[..., Any]]:
    """Session-scoped factory for ephemeral HTTP/2 servers.

    Returns an async callable that creates and starts a new
    :class:`EphemeralHttp2Server` with the supplied keyword arguments.
    All servers created through the factory are stopped automatically
    at the end of the session.
    """
    servers: list[EphemeralHttp2Server] = []

    async def _create(**kwargs: object) -> EphemeralHttp2Server:
        s = EphemeralHttp2Server(**(kwargs))  # type: ignore[arg-type]
        await s.start()
        servers.append(s)
        return s

    yield _create

    for s in servers:
        await s.stop()


@pytest_asyncio.fixture
async def fast_server(
    http2_server_factory: Callable[..., Any],
) -> EphemeralHttp2Server:
    """Function-scoped server with no response delay and 100-stream limit."""
    return await http2_server_factory(
        max_concurrent_streams=100,
        response_delay_ms=0,
    )


@pytest_asyncio.fixture
async def slow_server(
    http2_server_factory: Callable[..., Any],
) -> EphemeralHttp2Server:
    """Function-scoped server with 2s response delay and 5-stream limit."""
    return await http2_server_factory(
        max_concurrent_streams=5,
        response_delay_ms=2000,
    )


@pytest.fixture
def collector_factory() -> Callable[..., MetricsCollector]:
    """Function-scoped factory for :class:`MetricsCollector`."""

    def _create(server: EphemeralHttp2Server) -> MetricsCollector:
        return MetricsCollector(server, trace_enabled=True)

    return _create
