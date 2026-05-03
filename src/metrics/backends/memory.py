"""In-memory metrics collector backend — for tests and local development.

No external dependencies (no ``prometheus_client``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from src.core.interfaces import IGauge, IMetricsCollector

if TYPE_CHECKING:
    from src.db.database import DatabaseManager


class _MemoryGauge(IGauge):
    """A single in-memory gauge value."""

    def __init__(self, name: str, labels: list[str]) -> None:
        self._name = name
        self._labels = labels
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        self._values[self._to_key(labels)] = value

    def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        self._values[self._to_key(labels)] += amount

    def _to_key(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        if labels is None:
            labels = {}
        return tuple(sorted(labels.items()))

    def snapshot(self) -> list[dict[str, object]]:
        """Return all label/value pairs for this gauge."""
        result: list[dict[str, object]] = []
        for label_tuple, value in self._values.items():
            result.append(
                {
                    "name": self._name,
                    "value": value,
                    "labels": dict(label_tuple),
                }
            )
        return result


class MemoryMetricsCollector(IMetricsCollector):
    """Metrics collector that stores everything in process memory.

    Designed for unit tests.  No I/O, no external services.
    """

    def __init__(self) -> None:
        self._gauges: dict[str, _MemoryGauge] = {}
        self._counters: dict[str, _MemoryGauge] = {}

    def gauge(self, name: str, description: str, labels: list[str]) -> IGauge:
        if name not in self._gauges:
            self._gauges[name] = _MemoryGauge(name, labels)
        return self._gauges[name]

    def counter(self, name: str, description: str, labels: list[str]) -> IGauge:
        if name not in self._counters:
            self._counters[name] = _MemoryGauge(name, labels)
        return self._counters[name]

    def generate_metrics(self) -> tuple[str, str]:
        """Return a simple JSON representation of all metrics."""
        items: list[dict[str, object]] = []
        for gauge_inst in self._gauges.values():
            items.extend(gauge_inst.snapshot())
        for counter_inst in self._counters.values():
            items.extend(counter_inst.snapshot())
        body = json.dumps({"metrics": items}, indent=2)
        return body, "application/json"

    async def collect_from_db(self, db_manager: DatabaseManager) -> None:
        """No-op: memory backend does not query the database."""
        pass
