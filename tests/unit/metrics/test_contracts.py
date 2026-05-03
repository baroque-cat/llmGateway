#!/usr/bin/env python3

"""Tests for metrics DTO dataclasses — UT-CT01, UT-CT02.

Verifies that ``GaugeSpec`` and ``MetricValue`` create correctly
and are frozen (immutable).
"""

import pytest

from src.metrics.contracts import GaugeSpec, MetricValue


# ---------------------------------------------------------------------------
# UT-CT01 — GaugeSpec creation
# ---------------------------------------------------------------------------


def test_gauge_spec_creates_correctly() -> None:
    """UT-CT01: GaugeSpec(name="test", description="desc", labels=["label1"]) creates correctly."""
    spec = GaugeSpec(name="test", description="desc", labels=["label1"])

    assert spec.name == "test"
    assert spec.description == "desc"
    assert spec.labels == ["label1"]


def test_gauge_spec_is_frozen() -> None:
    """GaugeSpec is frozen — attribute assignment raises FrozenInstanceError."""
    spec = GaugeSpec(name="test", description="desc", labels=["label1"])

    with pytest.raises(AttributeError):
        spec.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# UT-CT02 — MetricValue creation
# ---------------------------------------------------------------------------


def test_metric_value_creates_correctly() -> None:
    """UT-CT02: MetricValue(name="test", value=5.0, labels={"k": "v"}) creates correctly."""
    mv = MetricValue(name="test", value=5.0, labels={"k": "v"})

    assert mv.name == "test"
    assert mv.value == 5.0
    assert mv.labels == {"k": "v"}


def test_metric_value_accepts_int() -> None:
    """MetricValue accepts int as well as float for the value field."""
    mv = MetricValue(name="test", value=42, labels={"k": "v"})

    assert mv.value == 42
    assert isinstance(mv.value, int)


def test_metric_value_is_frozen() -> None:
    """MetricValue is frozen — attribute assignment raises FrozenInstanceError."""
    mv = MetricValue(name="test", value=5.0, labels={"k": "v"})

    with pytest.raises(AttributeError):
        mv.value = 10.0  # type: ignore[misc]