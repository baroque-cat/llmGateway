#!/usr/bin/env python3

"""Tests for PrometheusMetricsCollector — UT-PB01 through UT-PB06 + removal verification.

Verifies single-process and multiprocess modes, gauge registration,
metric generation, DB collection, metric name consistency, and
model label removal.
"""

import inspect
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.core import REGISTRY, CollectorRegistry

from src.core.interfaces import IGauge
from src.metrics.backends import prometheus as prometheus_module
from src.metrics.backends.prometheus import PrometheusMetricsCollector
from src.metrics.registry import (
    DB_DEAD_TUPLES,
    KEY_STATUS_TOTAL,
    METRIC_DESCRIPTIONS,
)

# ---------------------------------------------------------------------------
# UT-PB01 — Single-process gauge() registers in REGISTRY
# ---------------------------------------------------------------------------


def test_single_process_gauge_registers_in_registry() -> None:
    """UT-PB01: PrometheusMetricsCollector (single-process) → gauge() registers in REGISTRY."""
    name = "test_ut_pb01_gauge"
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
    name = "test_ut_pb02_gauge"
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
        collector = PrometheusMetricsCollector(multiprocess_dir=tmpdir)

        # Should have a private registry (not the global REGISTRY)
        assert collector._registry is not REGISTRY  # type: ignore[reportPrivateUsage]
        assert collector._multiprocess_dir == tmpdir  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# UT-PB04 — Multiprocess → gauge() creates IGauge
# ---------------------------------------------------------------------------


def test_multiprocess_gauge_creates_igauge() -> None:
    """UT-PB04: Multiprocess mode → gauge() returns an IGauge instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        collector = PrometheusMetricsCollector(multiprocess_dir=tmpdir)
        name = "test_ut_pb04_gauge"
        gauge = collector.gauge(name, "Test gauge", [])

        assert isinstance(gauge, IGauge)


# ---------------------------------------------------------------------------
# UT-PB05 — collect_from_db() with mock DatabaseManager → updates gauge values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_from_db_updates_gauge_values() -> None:
    """UT-PB05: collect_from_db() updates KEY_STATUS_TOTAL with provider+status only (no model label)."""
    # Use a private registry to avoid polluting the global REGISTRY
    private_registry = CollectorRegistry()
    collector = PrometheusMetricsCollector.__new__(PrometheusMetricsCollector)
    collector._multiprocess_dir = None  # type: ignore[reportPrivateUsage]
    collector._gauges = {}  # type: ignore[reportPrivateUsage]
    collector._counters = {}  # type: ignore[reportPrivateUsage]
    collector._registry = private_registry  # type: ignore[reportPrivateUsage]

    # Mock db_manager — StatusSummaryItem no longer has a "model" field
    mock_db = MagicMock()
    mock_db.keys = MagicMock()
    mock_db.keys.get_status_summary = AsyncMock(
        return_value=[
            {"provider": "openai", "status": "valid", "count": 5},
            {"provider": "anthropic", "status": "valid", "count": 3},
            {"provider": "openai", "status": "invalid", "count": 2},
        ]
    )

    await collector.collect_from_db(mock_db)

    # KEY_STATUS_TOTAL should now be in the collector's gauges
    assert KEY_STATUS_TOTAL in collector._gauges  # type: ignore[reportPrivateUsage]

    # Verify the mock was called
    mock_db.keys.get_status_summary.assert_called_once()

    # Verify gauge values set with provider and status only
    raw_gauge = collector._gauges[KEY_STATUS_TOTAL]  # type: ignore[reportPrivateUsage]
    assert raw_gauge.labels(provider="openai", status="valid")._value.get() == 5.0
    assert raw_gauge.labels(provider="anthropic", status="valid")._value.get() == 3.0
    assert raw_gauge.labels(provider="openai", status="invalid")._value.get() == 2.0

    # Verify generated metrics output contains no "model" label
    body, _ = collector.generate_metrics()
    output = body.decode("utf-8")
    assert "model=" not in output


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


# ---------------------------------------------------------------------------
# Removal verification — gauge registered without model label
# ---------------------------------------------------------------------------


def test_gauge_registered_without_model_label() -> None:
    """KEY_STATUS_TOTAL gauge is registered with provider and status labels only (no model)."""
    private_registry = CollectorRegistry()
    collector = PrometheusMetricsCollector.__new__(PrometheusMetricsCollector)
    collector._multiprocess_dir = None  # type: ignore[reportPrivateUsage]
    collector._gauges = {}  # type: ignore[reportPrivateUsage]
    collector._counters = {}  # type: ignore[reportPrivateUsage]
    collector._registry = private_registry  # type: ignore[reportPrivateUsage]

    # Trigger gauge registration with the same labels used in collect_from_db
    collector.gauge(
        KEY_STATUS_TOTAL,
        METRIC_DESCRIPTIONS[KEY_STATUS_TOTAL],
        ["provider", "status"],
    )

    # The gauge must exist
    assert KEY_STATUS_TOTAL in collector._gauges  # type: ignore[reportPrivateUsage]

    # Verify label names — must be ("provider", "status"), NOT include "model"
    prom_gauge = collector._gauges[KEY_STATUS_TOTAL]  # type: ignore[reportPrivateUsage]
    assert prom_gauge._labelnames == ("provider", "status")

    # Set a value and verify the generated output has no "model" label
    prom_gauge.labels(provider="openai", status="valid").set(7.0)
    body, _ = collector.generate_metrics()
    output = body.decode("utf-8")
    assert "model=" not in output


# ---------------------------------------------------------------------------
# Removal verification — no model transformation code
# ---------------------------------------------------------------------------


def test_no_model_transformation_code() -> None:
    """No __ALL_MODELS__ → \"shared\" transformation code remains in prometheus.py."""
    source = inspect.getsource(prometheus_module)
    assert (
        "__ALL_MODELS__" not in source
    ), "prometheus.py still contains __ALL_MODELS__ transformation code"

    # Verify the collect_from_db method has no transformation logic
    collect_source = inspect.getsource(PrometheusMetricsCollector.collect_from_db)
    assert "__ALL_MODELS__" not in collect_source
    assert '"shared"' not in collect_source
