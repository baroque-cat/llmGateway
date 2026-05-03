#!/usr/bin/env python3

"""Tests for metrics ABC enforcement — UT-IF01 through UT-IF07.

Verifies that ``IMetricsCollector`` and ``IGauge`` cannot be
instantiated directly and that partial implementations raise
``TypeError``.
"""

import pytest

from src.core.interfaces import IGauge, IMetricsCollector


# ---------------------------------------------------------------------------
# UT-IF01 — IMetricsCollector() raises TypeError (abstract class)
# ---------------------------------------------------------------------------


def test_imetrics_collector_cannot_be_instantiated() -> None:
    """UT-IF01: Direct instantiation of IMetricsCollector raises TypeError."""
    with pytest.raises(TypeError, match="abstract method|cannot instantiate"):
        IMetricsCollector()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF02 — Class without gauge() → TypeError
# ---------------------------------------------------------------------------


def test_metrics_collector_without_gauge_raises_typeerror() -> None:
    """UT-IF02: Subclass missing gauge() raises TypeError on instantiation."""

    class _Partial(IMetricsCollector):
        def counter(self, name: str, description: str, labels: list[str]) -> IGauge:
            return _StubGauge()

        def generate_metrics(self) -> tuple[bytes | str, str]:
            return b"", "text/plain"

        async def collect_from_db(self, db_manager: object) -> None:
            pass

    with pytest.raises(TypeError, match="gauge"):
        _Partial()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF03 — Class without generate_metrics() → TypeError
# ---------------------------------------------------------------------------


def test_metrics_collector_without_generate_metrics_raises_typeerror() -> None:
    """UT-IF03: Subclass missing generate_metrics() raises TypeError."""

    class _Partial(IMetricsCollector):
        def gauge(self, name: str, description: str, labels: list[str]) -> IGauge:
            return _StubGauge()

        def counter(self, name: str, description: str, labels: list[str]) -> IGauge:
            return _StubGauge()

        async def collect_from_db(self, db_manager: object) -> None:
            pass

    with pytest.raises(TypeError, match="generate_metrics"):
        _Partial()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF04 — Class without collect_from_db() → TypeError
# ---------------------------------------------------------------------------


def test_metrics_collector_without_collect_from_db_raises_typeerror() -> None:
    """UT-IF04: Subclass missing collect_from_db() raises TypeError."""

    class _Partial(IMetricsCollector):
        def gauge(self, name: str, description: str, labels: list[str]) -> IGauge:
            return _StubGauge()

        def counter(self, name: str, description: str, labels: list[str]) -> IGauge:
            return _StubGauge()

        def generate_metrics(self) -> tuple[bytes | str, str]:
            return b"", "text/plain"

    with pytest.raises(TypeError, match="collect_from_db"):
        _Partial()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF05 — IGauge() raises TypeError (abstract class)
# ---------------------------------------------------------------------------


def test_igauge_cannot_be_instantiated() -> None:
    """UT-IF05: Direct instantiation of IGauge raises TypeError."""
    with pytest.raises(TypeError, match="abstract method|cannot instantiate"):
        IGauge()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF06 — Class without set() → TypeError
# ---------------------------------------------------------------------------


def test_igauge_without_set_raises_typeerror() -> None:
    """UT-IF06: Subclass missing set() raises TypeError."""

    class _Partial(IGauge):
        def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
            pass

    with pytest.raises(TypeError, match="set"):
        _Partial()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# UT-IF07 — Class without inc() → TypeError
# ---------------------------------------------------------------------------


def test_igauge_without_inc_raises_typeerror() -> None:
    """UT-IF07: Subclass missing inc() raises TypeError."""

    class _Partial(IGauge):
        def set(self, value: float, labels: dict[str, str] | None = None) -> None:
            pass

    with pytest.raises(TypeError, match="inc"):
        _Partial()  # type: ignore[reportAbstractUsage]


# ---------------------------------------------------------------------------
# Helper — minimal IGauge stub for partial IMetricsCollector tests
# ---------------------------------------------------------------------------


class _StubGauge(IGauge):
    """Minimal IGauge implementation used by partial collector tests."""

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        pass

    def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        pass