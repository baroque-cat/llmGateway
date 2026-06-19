"""Stress test: validate the httpcore HTTP/2 stream desync patch.

Verifies that after mass cancellation of in-flight HTTP/2 requests,
httpcore and h2 stream counts stay in sync — follow-up requests on
the same connection must succeed rather than failing with
``LocalProtocolError: Max outbound streams``.

This test targets the bug fixed by
``src/core/httpcore_patch.py`` (encode/httpcore#1022).

Uses raw httpcore (not httpx) because httpx 0.28.1 catches
CancelledError at its own level and properly closes streams, masking
the desync bug.  The production bug manifests when httpcore tasks are
cancelled from the outside (e.g. by asyncio.timeout in the gateway
retry loop).
"""

from __future__ import annotations

import asyncio
import ssl as _ssl
from collections.abc import Callable
from typing import Any

import httpcore
import pytest

from tests.stress.metrics import MetricsCollector

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_recovery_after_mass_cancellation(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """Mass cancellation must not desynchronise httpcore and h2 stream counts.

    Uses raw httpcore.AsyncConnectionPool (not httpx) to bypass
    httpx's own cancellation handling and hit httpcore's internal
    ``except BaseException`` path directly — the same path triggered
    by ``asyncio.timeout()`` in the gateway retry loop.
    """
    STREAM_LIMIT = 30
    CANCEL_COUNT = 25  # must open 25 streams (via send_headers), all cancelled
    FOLLOWUP_COUNT = 10  # 25 + 10 = 35 > 30 → must fail without patch
    BODY = b"x" * 4096  # 4 KB — enough for write contention

    server = await http2_server_factory(
        max_concurrent_streams=STREAM_LIMIT,
        response_delay_ms=30000,  # 30 s — never arrives during test
    )
    collector: MetricsCollector = collector_factory(server)

    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    ssl_ctx.set_alpn_protocols(["h2"])

    url = server.url  # "https://127.0.0.1:XXXXX"
    host = url.split("://")[1].split(":")[0]
    port = int(url.split(":")[-1])
    target = f"https://{host}:{port}/test"
    headers = [(b"host", f"{host}:{port}".encode())]

    async with httpcore.AsyncConnectionPool(
        http2=True,
        max_connections=1,
        ssl_context=ssl_ctx,
    ) as pool:
        # --- Phase 1: mass cancellation (reproduction of #1022) ---
        tasks = []
        for _ in range(CANCEL_COUNT):
            tasks.append(
                asyncio.create_task(
                    pool.request("POST", target, headers=headers, content=BODY)
                )
            )

        await asyncio.sleep(0.15)
        for t in tasks:
            t.cancel()

        cancelled = 0
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, asyncio.CancelledError):
                cancelled += 1

        assert cancelled >= CANCEL_COUNT - 2, (
            f"Expected most cancelled, got {cancelled}/{CANCEL_COUNT}"
        )

        # Give the event loop a tick so _response_closed runs.
        await asyncio.sleep(0.5)

        # --- Phase 2: follow-up requests on the SAME pool ---
        server.reset_metrics()
        collector.start()

        local_errors = 0
        successes = 0
        tasks2 = []
        for _ in range(FOLLOWUP_COUNT):
            tasks2.append(
                asyncio.create_task(
                    pool.request("GET", target, headers=headers)
                )
            )
        results2 = await asyncio.gather(*tasks2, return_exceptions=True)
        for r in results2:
            if isinstance(r, httpcore.Response):
                successes += 1
                await r.aclose()
            elif isinstance(r, Exception):
                if isinstance(r, httpcore.LocalProtocolError):
                    local_errors += 1

    metrics = collector.stop()

    print(
        f"\n[test_desync_patch] "
        f"phase1_cancelled={cancelled}/{CANCEL_COUNT} "
        f"phase2_successes={successes}/{FOLLOWUP_COUNT} "
        f"phase2_local_protocol_errors={local_errors} "
        f"server_peak_streams={metrics.server_peak_streams}"
    )

    # KEY assertion — with the patch, all follow-ups succeed.
    # Without the patch, httpcore's semaphore is released but h2
    # still counts the cancelled streams → LocalProtocolError.
    assert successes == FOLLOWUP_COUNT, (
        f"After mass cancellation, expected {FOLLOWUP_COUNT} follow-up "
        f"requests to succeed, but only {successes} succeeded "
        f"(local_protocol_errors={local_errors})."
    )

    assert local_errors == 0, (
        f"Expected 0 LocalProtocolError in phase 2, got {local_errors}"
    )

    assert metrics.server_peak_streams <= FOLLOWUP_COUNT, (
        f"Peak streams during phase 2 should be ≤ {FOLLOWUP_COUNT}, "
        f"got {metrics.server_peak_streams}"
    )
