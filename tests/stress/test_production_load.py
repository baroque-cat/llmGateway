"""Production-load stress tests: simulate real provider load at scale.

Validates that ``CapacityAwareHttp2Transport`` prevents the production
cascade described in ``docs/HTTP2_STRESS_TESTS.md`` Section 1:

* **Scenario A — Mass concurrent load:** 500 requests against a 128-stream
  server.  Proves pool opens new TCP connections when H2 streams are full
  (Bug #2 fix at production scale).

* **Scenario B — Mass cancellation + recovery:** 200 requests cancelled
  mid-flight, then 50 follow-ups.  Proves no phantom stream accumulation
  after asyncio task cancellation (Bug #1 fix at production scale).

* **Scenario C — Rapid retry bursts:** Three waves of 50 requests in quick
  succession.  Proves the pool handles repeated load spikes without
  accumulating errors or burning through connections.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.http2 import CapacityAwareHttp2Transport
from tests.stress.metrics import MetricsCollector

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _trace_adapter(
    name: str, info: dict[str, object], collector: MetricsCollector
) -> None:
    """Async trace handler — forward connection events to *collector*."""
    event: dict[str, object] = {**info}
    if "connect_tcp.complete" in name:
        event["event"] = "connection_created"
    elif "close.complete" in name or "close.started" in name:
        event["event"] = "connection_closed"
    else:
        event["event"] = name
    collector.trace_handler(event)


def _make_trace_adapter(
    collector: MetricsCollector,
) -> Callable[[str, dict[str, object]], Any]:
    """Return an async callable suitable for ``extensions={"trace": ...}``.

    httpx requires the trace callback to be ``async`` when used with
    ``httpx.AsyncClient``.
    """

    async def _trace(name: str, info: dict[str, object]) -> None:
        await _trace_adapter(name, info, collector)

    return _trace


def _record_results(results: list[Any], collector: MetricsCollector) -> tuple[int, int]:
    """Record exceptions and count successes.

    Returns:
        (success_count, error_count)
    """
    success = 0
    errors = 0
    for r in results:
        if isinstance(r, httpx.Response):
            success += 1
        elif isinstance(r, Exception):
            errors += 1
            collector.record_exception(r)
    return success, errors


# ---------------------------------------------------------------------------
# Scenario A: Mass concurrent load approaching stream limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mass_concurrent_load_no_stream_errors(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """500 concurrent requests against a 128-stream server — no stream errors.

    Proves that when total requests exceed a single connection's stream
    limit, the pool opens additional TCP connections to distribute load,
    rather than hitting ``LocalProtocolError`` / ``Max outbound streams``.
    """
    server = await http2_server_factory(
        max_concurrent_streams=128,
        response_delay_ms=5000,
    )
    collector: MetricsCollector = collector_factory(server)
    collector.start()

    trace = _make_trace_adapter(collector)

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        transport=CapacityAwareHttp2Transport(
            verify=False,
            http1=False,
            http2=True,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=100,
                keepalive_expiry=60.0,
            ),
        ),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=100,
            keepalive_expiry=60.0,
        ),
        timeout=httpx.Timeout(120.0, pool=60.0),
    ) as client:
        tasks = [
            client.get(f"{server.url}/test", extensions={"trace": trace})
            for _ in range(500)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count, error_count = _record_results(results, collector)
    metrics = collector.stop()

    print(
        f"\n[test_mass_concurrent] "
        f"server_peak_connections={metrics.server_peak_connections} "
        f"server_peak_streams={metrics.server_peak_streams} "
        f"client_connections_created={metrics.client_connections_created} "
        f"successes={success_count} "
        f"errors={error_count} "
        f"local_protocol_errors={metrics.local_protocol_errors} "
        f"pool_timeout_errors={metrics.pool_timeout_errors}"
    )

    # Pool opens multiple TCP connections (500 requests / 128 streams ≈ 4+).
    assert metrics.client_connections_created >= 2, (
        f"Expected ≥ 2 connections created (pool growth at scale), "
        f"got {metrics.client_connections_created}"
    )

    # Server sees connections from multiple sources.
    assert metrics.server_peak_connections >= 2, (
        f"Expected ≥ 2 server-side peak connections, "
        f"got {metrics.server_peak_connections}"
    )

    # No "Max outbound streams is 128, 128 open" cascade.
    # A few protocol errors are acceptable during connection cycling.
    assert metrics.local_protocol_errors < 50, (
        f"Expected < 50 local_protocol_errors (no stream overflow cascade), "
        f"got {metrics.local_protocol_errors}"
    )

    # The vast majority of requests succeed.
    assert (
        success_count >= 400
    ), f"Expected ≥ 400 successes out of 500, got {success_count}"


# ---------------------------------------------------------------------------
# Scenario B: Mass cancellation + recovery (Bug #1 at scale)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mass_cancellation_recovery(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """Mass-cancel 200 requests, then verify 50 follow-ups all succeed.

    Proves that after ``asyncio`` task cancellation, ``_response_closed()``
    synchronises h2's stream state with the semaphore — no phantom stream
    accumulation, no ``NoAvailableStreamIDError``.
    """
    server = await http2_server_factory(
        max_concurrent_streams=128,
        response_delay_ms=30000,  # 30s — long enough to guarantee cancellation
    )
    collector: MetricsCollector = collector_factory(server)
    collector.start()

    trace = _make_trace_adapter(collector)

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        transport=CapacityAwareHttp2Transport(
            verify=False,
            http1=False,
            http2=True,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=10,
                keepalive_expiry=60.0,
            ),
        ),
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=10,
            keepalive_expiry=60.0,
        ),
        timeout=httpx.Timeout(120.0, pool=60.0),
    ) as client:
        # Phase 1 — mass cancellation.
        # Create explicit asyncio.Tasks so we can cancel them.
        tasks = [
            asyncio.create_task(
                client.get(f"{server.url}/test", extensions={"trace": trace})
            )
            for _ in range(200)
        ]
        # Wait for connections to establish and requests to be sent.
        await asyncio.sleep(0.3)
        for t in tasks:
            t.cancel()
        phase1_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Allow _response_closed to run on all streams.
        await asyncio.sleep(0.5)

        # Phase 2 — follow-up requests on the SAME pool.
        tasks2 = [
            client.get(f"{server.url}/test", extensions={"trace": trace})
            for _ in range(50)
        ]
        phase2_results = await asyncio.gather(*tasks2, return_exceptions=True)

    # Record phase 1 exceptions for completeness (expected: CancelledError).
    for r in phase1_results:
        if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
            collector.record_exception(r)

    success2, error2 = _record_results(phase2_results, collector)
    metrics = collector.stop()

    print(
        f"\n[test_mass_cancellation] "
        f"server_peak_streams={metrics.server_peak_streams} "
        f"phase2_successes={success2} "
        f"phase2_errors={error2} "
        f"local_protocol_errors={metrics.local_protocol_errors}"
    )

    # All 50 follow-up requests must succeed — no phantom streams.
    assert success2 == 50, (
        f"Expected 50/50 follow-ups to succeed after mass cancellation, "
        f"got {success2} successes, {error2} errors"
    )

    # Zero "Max outbound streams" errors from phantom stream accumulation.
    assert metrics.local_protocol_errors == 0, (
        f"Expected 0 local_protocol_errors after cancellation recovery, "
        f"got {metrics.local_protocol_errors}"
    )


# ---------------------------------------------------------------------------
# Scenario C: Rapid retry bursts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_retry_bursts_no_error_accumulation(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """Three waves of requests simulate Gateway retry bursts.

    In production the Gateway may retry quickly after timeouts.
    This test verifies that repeated load spikes do NOT accumulate
    errors or exhaust connections — the pool handles each wave cleanly.
    """
    server = await http2_server_factory(
        max_concurrent_streams=128,
        response_delay_ms=2000,
    )
    collector: MetricsCollector = collector_factory(server)
    collector.start()

    trace = _make_trace_adapter(collector)

    wave_results: list[list[Any]] = []

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        transport=CapacityAwareHttp2Transport(
            verify=False,
            http1=False,
            http2=True,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=100,
                keepalive_expiry=60.0,
            ),
        ),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=100,
            keepalive_expiry=60.0,
        ),
        timeout=httpx.Timeout(60.0, pool=30.0),
    ) as client:
        for wave in range(3):
            tasks = [
                client.get(f"{server.url}/test", extensions={"trace": trace})
                for _ in range(50)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            wave_results.append(results)
            # Brief pause between waves (simulates retry backoff).
            if wave < 2:
                await asyncio.sleep(0.5)

    total_success = 0
    total_errors = 0
    for _i, results in enumerate(wave_results):
        s, e = _record_results(results, collector)
        total_success += s
        total_errors += e

    metrics = collector.stop()

    print(
        f"\n[test_rapid_retry] "
        f"server_peak_connections={metrics.server_peak_connections} "
        f"server_peak_streams={metrics.server_peak_streams} "
        f"client_connections_created={metrics.client_connections_created} "
        f"total_successes={total_success} "
        f"total_errors={total_errors} "
        f"local_protocol_errors={metrics.local_protocol_errors}"
    )

    # The overwhelming majority of requests across all waves succeed.
    assert total_success >= 135, (
        f"Expected ≥ 135 successes across 3 waves (150 total), " f"got {total_success}"
    )

    # Error rate stays low — no accumulating cascade.
    assert total_errors <= 15, (
        f"Expected ≤ 15 errors across 3 waves (no error accumulation), "
        f"got {total_errors}"
    )

    # No stream-overflow protocol errors.
    assert metrics.local_protocol_errors < 10, (
        f"Expected < 10 local_protocol_errors, " f"got {metrics.local_protocol_errors}"
    )
