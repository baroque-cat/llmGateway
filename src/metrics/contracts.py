"""DTOs (Data Transfer Objects) for the metrics layer.

These dataclasses carry metric specifications and values
between the application layer and metric backends without
pulling ``prometheus_client`` into business code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GaugeSpec:
    """Specification for registering a gauge.

    Attributes:
        name: Unique metric name (e.g. ``"llm_gateway_keys_total"``).
        description: Human-readable help text for the metric.
        labels: Label dimension names.
    """

    name: str
    description: str
    labels: list[str]


@dataclass(frozen=True)
class MetricValue:
    """A single metric data point produced by ``generate_metrics()``.

    Attributes:
        name: Metric name.
        value: Numeric value (float or int).
        labels: Optional label key-value pairs.
    """

    name: str
    value: float | int
    labels: dict[str, str]
