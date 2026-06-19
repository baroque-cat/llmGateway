"""Stress test: keepalive connection expiry forces new connection creation
for sequential requests with long gaps.

Verifies that httpx respects the keepalive_expiry setting and creates fresh
connections when the idle period between requests exceeds the expiry threshold.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.stress.ephemeral_api import EphemeralHttp2Server
from tests.stress.metrics import MetricsCollector

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_connections_expire_between_sequential_requests(
    fast_server: EphemeralHttp2Server,
    collector_factory: Callable[..., Any],
) -> None:
    """Assert that keepalive_expiry forces fresh connections for sequential requests.

    Sends 20 sequential GET requests with a 6-second gap between each.  The
    client's keepalive_expiry is set to 5 seconds, so each connection expires
    before the next request arrives.  Expect at least 10 connections created.
    """
    collector: MetricsCollector = collector_factory(fast_server)
    collector.start()

    async def _trace_adapter(name: str, info: dict[str, object]) -> None:
        event: dict[str, object] = {**info}
        if "connect_tcp.complete" in name:
            event["event"] = "connection_created"
        elif "close.complete" in name or "close.started" in name:
            event["event"] = "connection_closed"
        else:
            event["event"] = name
        collector.trace_handler(event)

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        limits=httpx.Limits(
            keepalive_expiry=5.0,
            max_keepalive_connections=20,
        ),
        timeout=httpx.Timeout(10.0),
    ) as client:
        for i in range(20):
            response = await client.get(
                f"{fast_server.url}/test",
                extensions={"trace": _trace_adapter},
            )
            assert response.status_code == 200
            if i < 19:  # no need to sleep after the last request
                await asyncio.sleep(6.0)

    metrics = collector.stop()

    print(
        f"\n[test_keepalive_churn] "
        f"client_connections_created={metrics.client_connections_created}"
    )

    # With 5s keepalive expiry and 6s gaps, every sequential pair needs a new
    # connection.  At minimum we expect 10+ connections over 20 requests.
    assert metrics.client_connections_created >= 10, (
        f"Expected ≥ 10 connections created due to 5s keepalive expiry, "
        f"got {metrics.client_connections_created}"
    )
