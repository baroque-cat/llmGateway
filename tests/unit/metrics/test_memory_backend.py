#!/usr/bin/env python3

"""Tests for MemoryMetricsCollector — UT-MB01 through UT-MB06.

Verifies the in-memory metrics backend: gauge creation, set/inc
operations, instance isolation, labelled metrics, and collect_from_db
no-op behaviour.
"""

from unittest.mock import MagicMock

import pytest

from src.core.interfaces import IGauge
from src.metrics.backends.memory import MemoryMetricsCollector


# ---------------------------------------------------------------------------
# UT-MB01 — gauge() returns IGauge
# ---------------------------------------------------------------------------


def test_gauge_returns_igauge() -> None:
    """UT-MB01: MemoryMetricsCollector().gauge() returns an IGauge instance."""
    collector = MemoryMetricsCollector()
    gauge = collector.gauge("test", "A test gauge", [])

    assert isinstance(gauge, IGauge)


# ---------------------------------------------------------------------------
# UT-MB02 — gauge.set(5.0) → generate_metrics() contains "test 5.0"
# ---------------------------------------------------------------------------


def test_gauge_set_appears_in_generate_metrics() -> None:
    """UT-MB02: After gauge.set(5.0), generate_metrics() output contains the value."""
    collector = MemoryMetricsCollector()
    gauge = collector.gauge("test", "A test gauge", [])

    gauge.set(5.0)

    body, content_type = collector.generate_metrics()
    assert content_type == "application/json"
    assert "test" in body
    assert "5.0" in body


# ---------------------------------------------------------------------------
# UT-MB03 — gauge.inc(2.0) after set(5.0) → generate_metrics() contains "7.0"
# ---------------------------------------------------------------------------


def test_gauge_inc_after_set() -> None:
    """UT-MB03: gauge.set(5.0) then gauge.inc(2.0) → output contains 7.0."""
    collector = MemoryMetricsCollector()
    gauge = collector.gauge("test", "A test gauge", [])

    gauge.set(5.0)
    gauge.inc(2.0)

    body, _ = collector.generate_metrics()
    assert "7.0" in body


# ---------------------------------------------------------------------------
# UT-MB04 — Two instances → metrics isolated
# ---------------------------------------------------------------------------


def test_two_instances_isolated() -> None:
    """UT-MB04: Two MemoryMetricsCollector instances have isolated metrics."""
    collector_a = MemoryMetricsCollector()
    collector_b = MemoryMetricsCollector()

    gauge_a = collector_a.gauge("test", "Gauge A", [])
    gauge_b = collector_b.gauge("test", "Gauge B", [])

    gauge_a.set(10.0)
    gauge_b.set(20.0)

    body_a, _ = collector_a.generate_metrics()
    body_b, _ = collector_b.generate_metrics()

    # collector_a should contain 10.0 but NOT 20.0
    assert "10.0" in body_a
    assert "20.0" not in body_a

    # collector_b should contain 20.0 but NOT 10.0
    assert "20.0" in body_b
    assert "10.0" not in body_b


# ---------------------------------------------------------------------------
# UT-MB05 — gauge.set(42.0, {"provider": "openai"}) → contains metric with label
# ---------------------------------------------------------------------------


def test_gauge_set_with_labels() -> None:
    """UT-MB05: gauge.set(42.0, {"provider": "openai"}) → output contains labelled metric."""
    collector = MemoryMetricsCollector()
    gauge = collector.gauge("test", "A test gauge", ["provider"])

    gauge.set(42.0, {"provider": "openai"})

    body, _ = collector.generate_metrics()
    assert "42.0" in body
    assert "openai" in body
    assert "provider" in body


# ---------------------------------------------------------------------------
# UT-MB06 — collect_from_db() → no exception (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_from_db_no_op() -> None:
    """UT-MB06: collect_from_db() does not raise any exception (no-op)."""
    collector = MemoryMetricsCollector()
    mock_db = MagicMock()

    # Should complete without raising
    await collector.collect_from_db(mock_db)