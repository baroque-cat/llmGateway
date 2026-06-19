"""Stress test: httpx connection pool recovers after a load spike subsides.

Verifies that after a high-concurrency burst that stresses the connection
pool, the pool returns to a healthy state capable of handling a modest
follow-up load without residual errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_pool_recovers_after_load_reduction(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert the connection pool recovers after a 50-request burst.

    Phase 1 sends 50 concurrent requests.  Some may fail under load — that
    is acceptable.  After a 30-second cooldown, Phase 2 sends 5 requests,
    all of which must succeed, demonstrating pool recovery.
    """
    server = await http2_server_factory(
        max_concurrent_streams=10,
        response_delay_ms=200,
    )

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=10,
        ),
        timeout=httpx.Timeout(30.0, pool=30.0),
    ) as client:
        # ---- Phase 1: high-concurrency burst ----
        phase1_tasks = [client.get(f"{server.url}/test") for _ in range(50)]
        phase1_results = await asyncio.gather(*phase1_tasks, return_exceptions=True)

        phase1_successes = sum(
            1 for r in phase1_results if isinstance(r, httpx.Response)
        )
        phase1_failures = len(phase1_results) - phase1_successes

        # ---- Cooldown: allow pool to drain and connections to settle ----
        await asyncio.sleep(30.0)

        # ---- Phase 2: modest follow-up load ----
        phase2_tasks = [client.get(f"{server.url}/test") for _ in range(5)]
        phase2_results = await asyncio.gather(*phase2_tasks, return_exceptions=True)

        phase2_successes = sum(
            1 for r in phase2_results if isinstance(r, httpx.Response)
        )

    final_stats = server.stats

    print(
        f"\n[test_pool_recovery] "
        f"phase1_successes={phase1_successes} "
        f"phase1_failures={phase1_failures} "
        f"phase2_successes={phase2_successes} "
        f"final_active_connections={final_stats['active_connections']} "
        f"final_peak_connections={final_stats['peak_connections']}"
    )

    # Phase 2: all 5 requests must succeed after recovery.
    assert phase2_successes == 5, (
        f"Expected all 5 Phase 2 requests to succeed after recovery, "
        f"got {phase2_successes}"
    )

    # After recovery, active connections should be minimal.
    assert final_stats["active_connections"] <= 1, (
        f"Expected ≤ 1 active connections after recovery, "
        f"got {final_stats['active_connections']}"
    )
