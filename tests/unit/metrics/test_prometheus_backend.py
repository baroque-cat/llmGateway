#!/usr/bin/env python3

"""Tests for PrometheusMetricsCollector — UT-PB01 through UT-PB06.

Verifies single-process and multiprocess modes, gauge registration,
metric generation, DB collection, and metric name consistency.
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.core import CollectorRegistry, REGISTRY

from src.core.interfaces import IGauge
from src.metrics.backends.prometheus import PrometheusMetricsCollector
from src.metrics.registry import (
    DB_DEAD_TUPLES,
    KEY_STATUS_TOTAL,
    METRIC_DESCRIPTIONS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_unique_name(base: str) -> str:
    """Append a counter to a base name to avoid Prometheus duplicate registration."""
    _counter = getattr(_make_unique_name, "_c", 0) + 1
    _make_unique_name._c = _counter  # type: ignore[attr-defined]
    return f"{base}_{_counter}"


# ---------------------------------------------------------------------------
# UT-PB01 — Single-process gauge() registers in REGISTRY
# ---------------------------------------------------------------------------


def test_single_process_gauge_registers_in_registry() -> None:
    """UT-PB01: PrometheusMetricsCollector (single-process) → gauge() registers in REGISTRY."""
    name = _make_unique_name("test_ut_pb01_gauge")
    collector = PrometheusMetricsCollector()  # single-process → uses REGISTRY

    gauge = collector.gauge(name, "Test gauge", [])

    assert isinstance(gauge, IGauge)
    # The gauge should be present in the collector's internal dict
    assert name in collector._gauges  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# UT-PB02 — generate_metrics() returns (body, content_type)
# ---------------------------------------------------------------------------


def test_generate_metrics_returns_body_and_content_type() -> None:
    """UT-PB02: generate_metrics() returns a tuple of (body, content_type)."""
    collector = PrometheusMetricsCollector()
    name = _make_unique_name("test_ut_pb02_gauge")
    gauge = collector.gauge(name, "Test gauge", [])
    gauge.set(1.0)

    body, content_type = collector.generate_metrics()

    assert isinstance(body, bytes)
    assert len(body) > 0
    assert content_type == CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# UT-PB03 — Multiprocess mode with PROMETHEUS_MULTIPROC_DIR → aggregates
# ---------------------------------------------------------------------------


def test_multiprocess_mode_aggregates() -> None:
    """UT-PB03: Multiprocess mode with PROMETHEUS_MULTIPROC_DIR → uses MultiProcessCollector."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_val = os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

        collector = PrometheusMetricsCollector(multiprocess_dir=tmpdir)

        # Should have a private registry (not the global REGISTRY)
        assert collector._registry is not REGISTRY  # type: ignore[reportPrivateUsage]
        assert collector._multiprocess_dir == tmpdir  # type: ignore[reportPrivateUsage]

        if old_val is not None:
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = old_val
        else:
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


# ---------------------------------------------------------------------------
# UT-PB04 — Multiprocess → gauge() creates IGauge
# ---------------------------------------------------------------------------


def test_multiprocess_gauge_creates_igauge() -> None:
    """UT-PB04: Multiprocess mode → gauge() returns an IGauge instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_val = os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

        collector = PrometheusMetricsCollector(multiprocess_dir=tmpdir)
        name = _make_unique_name("test_ut_pb04_gauge")
        gauge = collector.gauge(name, "Test gauge", [])

        assert isinstance(gauge, IGauge)

        if old_val is not None:
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = old_val
        else:
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


# ---------------------------------------------------------------------------
# UT-PB05 — collect_from_db() with mock DatabaseManager → updates gauge values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_from_db_updates_gauge_values() -> None:
    """UT-PB05: collect_from_db() with mock DatabaseManager → updates KEY_STATUS_TOTAL gauge."""
    # Use a private registry to avoid polluting the global REGISTRY
    private_registry = CollectorRegistry()
    collector = PrometheusMetricsCollector.__new__(PrometheusMetricsCollector)
    collector._multiprocess_dir = None  # type: ignore[reportPrivateUsage]
    collector._gauges = {}  # type: ignore[reportPrivateUsage]
    collector._counters = {}  # type: ignore[reportPrivateUsage]
    collector._registry = private_registry  # type: ignore[reportPrivateUsage]

    # Mock db_manager
    mock_db = MagicMock()
    mock_db.keys = MagicMock()
    mock_db.keys.get_status_summary = AsyncMock(
        return_value=[
            {"provider": "openai", "model": "gpt-4", "status": "valid", "count": 5},
            {"provider": "anthropic", "model": "__ALL_MODELS__", "status": "valid", "count": 3},
        ]
    )

    await collector.collect_from_db(mock_db)

    # KEY_STATUS_TOTAL should now be in the collector's gauges
    assert KEY_STATUS_TOTAL in collector._gauges  # type: ignore[reportPrivateUsage]

    # Verify the mock was called
    mock_db.keys.get_status_summary.assert_called_once()


# ---------------------------------------------------------------------------
# UT-PB06 — Metric names in output match registry constants
# ---------------------------------------------------------------------------


def test_metric_names_in_output_match_registry() -> None:
    """UT-PB06: Registered metric names appear in generate_metrics() output."""
    # Use a private registry to avoid collisions
    private_registry = CollectorRegistry()
    collector = PrometheusMetricsCollector.__new__(PrometheusMetricsCollector)
    collector._multiprocess_dir = None  # type: ignore[reportPrivateUsage]
    collector._gauges = {}  # type: ignore[reportPrivateUsage]
    collector._counters = {}  # type: ignore[reportPrivateUsage]
    collector._registry = private_registry  # type: ignore[reportPrivateUsage]

    # Register a gauge using a registry constant name
    gauge = collector.gauge(
        DB_DEAD_TUPLES,
        METRIC_DESCRIPTIONS[DB_DEAD_TUPLES],
        ["table"],
    )
    gauge.set(100.0, {"table": "public.api_keys"})

    body, _ = collector.generate_metrics()

    # The output should contain the metric name from the registry
    assert DB_DEAD_TUPLES in body.decode("utf-8")