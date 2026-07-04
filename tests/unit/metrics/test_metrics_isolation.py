#!/usr/bin/env python3

"""Tests for metrics collector isolation via the autouse fixture.

Verifies that the ``_isolate_metrics_collector`` autouse fixture in
``tests/unit/metrics/conftest.py`` properly resets the collector
singleton and deletes relevant environment variables before and after
each test.

These tests run under the autouse fixture, so no explicit fixture
request is needed — the fixture handles cleanup automatically.
"""

import os

from src.metrics import get_collector
from src.metrics.backends.memory import MemoryMetricsCollector
from src.metrics.backends.prometheus import PrometheusMetricsCollector

# ---------------------------------------------------------------------------
# Autouse fixture resets collector and deletes env vars at test start
# ---------------------------------------------------------------------------


def test_autouse_fixture_resets_collector_and_deletes_env_vars() -> None:
    """At test start, env vars are deleted and collector singleton is fresh.

    The autouse ``_isolate_metrics_collector`` fixture calls
    ``reset_collector()`` and ``monkeypatch.delenv()`` for both
    ``METRICS_BACKEND`` and ``PROMETHEUS_MULTIPROC_DIR`` before the
    test body runs.
    """
    assert "METRICS_BACKEND" not in os.environ
    assert "PROMETHEUS_MULTIPROC_DIR" not in os.environ

    collector = get_collector()
    assert collector is not None
    assert isinstance(collector, PrometheusMetricsCollector)


# ---------------------------------------------------------------------------
# State set in one test does not leak to the next
# ---------------------------------------------------------------------------


def test_collector_state_set_in_one_test_does_not_leak() -> None:
    """Deliberately set METRICS_BACKEND=memory and verify MemoryMetricsCollector.

    This test sets state that the autouse fixture should clean up
    after the test completes.
    """
    os.environ["METRICS_BACKEND"] = "memory"
    collector = get_collector()
    assert isinstance(collector, MemoryMetricsCollector)


# ---------------------------------------------------------------------------
# State from the previous test is gone
# ---------------------------------------------------------------------------


def test_collector_state_from_previous_test_is_gone() -> None:
    """Verify that state from the previous test is cleaned up.

    The autouse fixture should have deleted ``METRICS_BACKEND`` and
    reset the collector singleton, so ``get_collector()`` returns a
    fresh ``PrometheusMetricsCollector`` (not the
    ``MemoryMetricsCollector`` from the previous test).
    """
    assert "METRICS_BACKEND" not in os.environ

    collector = get_collector()
    assert not isinstance(collector, MemoryMetricsCollector)
    assert isinstance(collector, PrometheusMetricsCollector)
