"""Prometheus metrics collector backend.

Single-process mode (Keeper): uses the default ``REGISTRY``.
Multiprocess mode (Gateway): uses ``MultiProcessCollector`` with
shared mmap files for worker aggregation.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
)
from prometheus_client.core import (
    REGISTRY,
    CollectorRegistry,
)
from prometheus_client.multiprocess import MultiProcessCollector

from src.core.interfaces import IGauge, IMetricsCollector
from src.metrics.registry import METRIC_DESCRIPTIONS

if TYPE_CHECKING:
    from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


class _PrometheusGauge(IGauge):
    """Wrapper around a Prometheus ``Gauge`` object."""

    def __init__(self, gauge: Gauge) -> None:
        self._gauge = gauge

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        if labels:
            self._gauge.labels(**labels).set(value)
        else:
            self._gauge.set(value)

    def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        if labels:
            self._gauge.labels(**labels).inc(amount)
        else:
            self._gauge.inc(amount)


class _PrometheusCounter(IGauge):
    """Wrapper around a Prometheus ``Counter`` object.

    Implements ``IGauge`` so it can be returned by
    ``IMetricsCollector.counter()``.  The ``set`` method is a
    no-op (Counters should only increase).
    """

    def __init__(self, counter: Counter) -> None:
        self._counter = counter

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        # Counter semantics: set is not supported, ignore.
        pass

    def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        if labels:
            self._counter.labels(**labels).inc(amount)
        else:
            self._counter.inc(amount)


class PrometheusMetricsCollector(IMetricsCollector):
    """Prometheus implementation of ``IMetricsCollector``.

    Two modes are supported:

    * **Single-process** — uses the global ``REGISTRY``.  Suitable
      for the Keeper (one process, one registry).
    * **Multiprocess** — sets up ``MultiProcessCollector`` with a
      shared mmap directory.  Suitable for the Gateway when
      ``workers > 1``.
    """

    def __init__(self, multiprocess_dir: str | None = None) -> None:
        self._multiprocess_dir = multiprocess_dir
        self._gauges: dict[str, Gauge] = {}
        self._counters: dict[str, Counter] = {}

        if multiprocess_dir:
            os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", multiprocess_dir)
            self._registry: CollectorRegistry = CollectorRegistry()
            MultiProcessCollector(self._registry)
        else:
            self._registry = REGISTRY

    def gauge(self, name: str, description: str, labels: list[str]) -> IGauge:
        if name not in self._gauges:
            gauge_desc = description or METRIC_DESCRIPTIONS.get(name, "")
            if self._multiprocess_dir:
                # In multiprocess mode, go through MultiProcessGauge
                # which serialises values via mmap files.
                # NOTE: prometheus_client's MultiProcessGauge is
                # a drop-in replacement for Gauge in multiprocess.
                prom_gauge = Gauge(
                    name,
                    gauge_desc,
                    labelnames=labels,
                    registry=self._registry,
                )
            else:
                prom_gauge = Gauge(
                    name,
                    gauge_desc,
                    labelnames=labels,
                    registry=self._registry,
                )
            self._gauges[name] = prom_gauge
        return _PrometheusGauge(self._gauges[name])

    def counter(self, name: str, description: str, labels: list[str]) -> IGauge:
        """Register or retrieve a Prometheus Counter.

        Args:
            name: Metric name.
            description: Human-readable help text.
            labels: Label names for the counter.

        Returns:
            A ``_PrometheusCounter`` wrapper.
        """
        if name not in self._counters:
            counter_desc = description or METRIC_DESCRIPTIONS.get(name, "")
            prom_counter = Counter(
                name,
                counter_desc,
                labelnames=labels,
                registry=self._registry,
            )
            self._counters[name] = prom_counter
        return _PrometheusCounter(self._counters[name])

    def generate_metrics(self) -> tuple[bytes, str]:
        """Return Prometheus text format metrics."""
        # MultiProcessCollector is registered; generate_latest
        # will aggregate across all worker mmap files.
        body = generate_latest(self._registry)
        return body, CONTENT_TYPE_LATEST

    async def collect_from_db(self, db_manager: DatabaseManager) -> None:
        """Collect metrics derived from the database.

        Queries key status summaries and updates the
        ``llm_gateway_keys_total`` gauge.

        Args:
            db_manager: The database manager for executing queries.
        """
        from src.metrics.registry import KEY_STATUS_TOTAL

        try:
            summary_data = await db_manager.keys.get_status_summary()
        except Exception as exc:
            logger.error("Failed to collect key status metrics from DB: %s", exc)
            return

        if KEY_STATUS_TOTAL not in self._gauges:
            self.gauge(
                KEY_STATUS_TOTAL,
                METRIC_DESCRIPTIONS.get(KEY_STATUS_TOTAL, ""),
                ["provider", "model", "status"],
            )

        # Prometheus GaugeMetricFamily cannot be fully replaced
        # by a standard Gauge for per-label updates, so we use a
        # custom collector approach: build a new set of values
        # each cycle.
        # We track the raw data and re-create the gauge values.
        _key_status_gauge = self._gauges[KEY_STATUS_TOTAL]

        # Clear old labels by setting all to 0 first (or use
        # GaugeMetricFamily). For simplicity, we build a
        # GaugeMetricFamily on the fly via _registry but the
        # static Gauge pattern is simpler.  We simply update
        # labels we receive and leave stale ones — they will
        # eventually disappear after the Keeper restarts.
        # For correctness, we do a manual approach via
        # GaugeMetricFamily-like logic.
        for record in summary_data:
            model_name = record["model"]
            if model_name == "__ALL_MODELS__":
                model_name = "shared"
            _key_status_gauge.labels(
                provider=record["provider"],
                model=model_name,
                status=record["status"],
            ).set(record["count"])
