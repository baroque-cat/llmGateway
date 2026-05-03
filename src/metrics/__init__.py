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


def reset_collector() -> None:
    """Reset the singleton (useful for tests)."""
    global _collector, _collector_env_snapshot
    _collector = None
    _collector_env_snapshot = {}
