#!/usr/bin/env python3

"""Tests for metrics factory (get_collector) — UT-FAC01 through UT-FAC05.

Verifies singleton behaviour, backend selection via env vars,
and singleton reset on env var changes.
"""

import os
import tempfile

import pytest

from src.metrics import get_collector, reset_collector
from src.metrics.backends.memory import MemoryMetricsCollector
from src.metrics.backends.prometheus import PrometheusMetricsCollector


# ---------------------------------------------------------------------------
# Helpers — clean up env and singleton before/after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env_and_singleton():  # type: ignore[reportUnusedFunction]
    """Reset the collector singleton and clean env vars before each test."""
    reset_collector()
    # Remove relevant env vars
    os.environ.pop("METRICS_BACKEND", None)
    os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
    yield
    # Clean up after test
    reset_collector()
    os.environ.pop("METRICS_BACKEND", None)
    os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


# ---------------------------------------------------------------------------
# UT-FAC01 — get_collector() twice → same object (singleton)
# ---------------------------------------------------------------------------


def test_get_collector_returns_singleton() -> None:
    """UT-FAC01: Calling get_collector() twice returns the same object."""
    a = get_collector()
    b = get_collector()
    assert a is b


# ---------------------------------------------------------------------------
# UT-FAC02 — METRICS_BACKEND=memory → MemoryMetricsCollector
# ---------------------------------------------------------------------------


def test_memory_backend_env_returns_memory_collector() -> None:
    """UT-FAC02: METRICS_BACKEND=memory → returns MemoryMetricsCollector."""
    os.environ["METRICS_BACKEND"] = "memory"
    collector = get_collector()
    assert isinstance(collector, MemoryMetricsCollector)


# ---------------------------------------------------------------------------
# UT-FAC03 — PROMETHEUS_MULTIPROC_DIR set → PrometheusMetricsCollector (multiprocess)
# ---------------------------------------------------------------------------


def test_multiproc_env_returns_prometheus_multiprocess() -> None:
    """UT-FAC03: PROMETHEUS_MULTIPROC_DIR set → returns PrometheusMetricsCollector with multiprocess."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmpdir
        collector = get_collector()
        assert isinstance(collector, PrometheusMetricsCollector)
        assert collector._multiprocess_dir is not None  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# UT-FAC04 — No env vars → PrometheusMetricsCollector (single-process)
# ---------------------------------------------------------------------------


def test_no_env_vars_returns_prometheus_single_process() -> None:
    """UT-FAC04: No env vars → returns PrometheusMetricsCollector (single-process)."""
    # Ensure both env vars are unset (fixture already does this)
    collector = get_collector()
    assert isinstance(collector, PrometheusMetricsCollector)
    assert collector._multiprocess_dir is None  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# UT-FAC05 — get_collector() after env var change → singleton reset
# ---------------------------------------------------------------------------


def test_env_change_resets_singleton() -> None:
    """UT-FAC05: Changing env vars causes get_collector() to return a new instance."""
    # First call — default (Prometheus single-process)
    first = get_collector()
    assert isinstance(first, PrometheusMetricsCollector)

    # Change env to memory backend
    os.environ["METRICS_BACKEND"] = "memory"

    # Second call — should detect env change and build a new collector
    second = get_collector()
    assert isinstance(second, MemoryMetricsCollector)
    assert second is not first