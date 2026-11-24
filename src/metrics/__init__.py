"""Metrics package entry point.

Provides a factory function ``get_collector()`` that returns
a singleton ``IMetricsCollector``.  The backend is selected
via environment variables:

* ``PROMETHEUS_MULTIPROC_DIR`` set → ``PrometheusMetricsCollector`` (multiprocess)
* ``METRICS_BACKEND=memory`` → ``MemoryMetricsCollector``
* Otherwise → ``PrometheusMetricsCollector`` (single-process)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.core.interfaces import IMetricsCollector

logger = logging.getLogger(__name__)

_collector: IMetricsCollector | None = None
_collector_env_snapshot: dict[str, str | None] = {}


def _env_changed() -> bool:
    """Check whether relevant env vars have changed since last instantiation."""
    current = {
        "PROMETHEUS_MULTIPROC_DIR": os.environ.get("PROMETHEUS_MULTIPROC_DIR"),
        "METRICS_BACKEND": os.environ.get("METRICS_BACKEND"),
    }
    return current != _collector_env_snapshot


def _build_collector() -> IMetricsCollector:
    """Build a new collector based on current environment."""
    backend = os.environ.get("METRICS_BACKEND")
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")

    if backend == "memory":
        from src.metrics.backends.memory import MemoryMetricsCollector

        logger.info("Metrics backend: memory (in-process)")
        return MemoryMetricsCollector()

    multiproc_dir_val = multiproc_dir or None

    from src.metrics.backends.prometheus import PrometheusMetricsCollector

    if multiproc_dir_val:
        logger.info(
            "Metrics backend: Prometheus (multiprocess, dir=%s)",
            multiproc_dir_val,
        )
    else:
        logger.info("Metrics backend: Prometheus (single-process)")

    return PrometheusMetricsCollector(multiprocess_dir=multiproc_dir_val)


def get_collector() -> IMetricsCollector:
    """Return the singleton ``IMetricsCollector`` instance.

    On first call, creates the collector based on environment
    variables.  Subsequent calls return the same instance unless
    the relevant env vars have changed (e.g. in tests).

    Returns:
        The singleton collector instance.
    """
    global _collector, _collector_env_snapshot

    if _collector is None or _env_changed():
        _collector = _build_collector()
        _collector_env_snapshot = {
            "PROMETHEUS_MULTIPROC_DIR": os.environ.get("PROMETHEUS_MULTIPROC_DIR"),
            "METRICS_BACKEND": os.environ.get("METRICS_BACKEND"),
        }

    return _collector


def emit_guard_transition(state: str, evidence: dict[str, Any]) -> None:
    """Update the network-guard metrics on an UP/DOWN transition.

    Args:
        state: ``"up"`` or ``"down"``.
        evidence: Transition evidence; ``reason`` is used as a counter label.
    """
    from src.metrics.registry import (  # local import avoids a cycle at import time
        METRIC_DESCRIPTIONS,
        NETWORK_GUARD_DOWN,
        NETWORK_GUARD_TRIPS_TOTAL,
    )

    try:
        collector = get_collector()
        collector.gauge(
            NETWORK_GUARD_DOWN, METRIC_DESCRIPTIONS[NETWORK_GUARD_DOWN], []
        ).set(1.0 if state == "down" else 0.0)
        if state == "down":
            collector.counter(
                NETWORK_GUARD_TRIPS_TOTAL,
                METRIC_DESCRIPTIONS[NETWORK_GUARD_TRIPS_TOTAL],
                ["reason"],
            ).inc(labels={"reason": str(evidence.get("reason", "unknown"))})
    except Exception:  # noqa: BLE001 - metrics must never break service startup
        logger.warning("Failed to emit network guard metrics", exc_info=True)


def reset_collector() -> None:
    """Reset the singleton (useful for tests)."""
    global _collector, _collector_env_snapshot
    _collector = None
    _collector_env_snapshot = {}
