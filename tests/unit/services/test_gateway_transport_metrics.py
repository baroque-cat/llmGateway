#!/usr/bin/env python3

"""
Tests for observe_upstream_attempt() metrics — UT-GTM01 through UT-GTM05.

Verifies that:
  - observe_upstream_attempt() increments upstream_attempts_total with correct labels
  - Transport failures increment transport_failures_total
  - Success does NOT increment transport_failures_total
  - Metric labels match provider name and outcome/transport_class
"""

from collections.abc import Generator
from typing import cast

import pytest

from src.core.constants import ErrorReason, TransportFailureClass
from src.core.models import CheckResult
from src.metrics.backends.memory import MemoryMetricsCollector
from src.metrics.registry import TRANSPORT_FAILURES_TOTAL, UPSTREAM_ATTEMPTS_TOTAL
from src.services.gateway.gateway_cache import observe_upstream_attempt


def _labels(entry: dict[str, object]) -> dict[str, str]:
    """Extract and cast the labels dict from a snapshot entry."""
    labels = entry.get("labels")
    assert isinstance(labels, dict)
    return cast(dict[str, str], labels)


@pytest.fixture
def memory_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[MemoryMetricsCollector]:
    """Provide a fresh MemoryMetricsCollector and patch get_collector() to return it."""
    from unittest.mock import patch

    collector = MemoryMetricsCollector()
    patcher = patch(
        "src.services.gateway.gateway_cache.get_collector", return_value=collector
    )
    patcher.start()
    yield collector  # type: ignore[misc]
    patcher.stop()


# ---------------------------------------------------------------------------
# UT-GTM01 — Success increments attempts_total with outcome=ok
# ---------------------------------------------------------------------------


def test_success_increments_attempts_with_ok(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """UT-GTM01: Successful result increments upstream_attempts_total with outcome=ok."""
    result = CheckResult.success()
    observe_upstream_attempt("test_provider", result)

    counter = memory_collector._counters.get(UPSTREAM_ATTEMPTS_TOTAL)  # type: ignore[attr-defined]
    assert counter is not None
    snapshot = counter.snapshot()  # type: ignore[attr-defined]

    # Find the entry with provider=test_provider, outcome=ok
    ok_entry = next(
        (
            s
            for s in snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("outcome") == "ok"
        ),
        None,
    )
    assert ok_entry is not None
    assert ok_entry["value"] == 1.0


# ---------------------------------------------------------------------------
# UT-GTM02 — Failure increments attempts_total with outcome=error_reason
# ---------------------------------------------------------------------------


def test_failure_increments_attempts_with_error_reason(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """UT-GTM02: Failed result increments upstream_attempts_total with outcome=error_reason.value."""
    result = CheckResult.fail(ErrorReason.TIMEOUT, "Timeout")
    observe_upstream_attempt("test_provider", result)

    counter = memory_collector._counters.get(UPSTREAM_ATTEMPTS_TOTAL)  # type: ignore[attr-defined]
    assert counter is not None
    snapshot = counter.snapshot()  # type: ignore[attr-defined]

    # Find the entry with provider=test_provider, outcome=timeout
    timeout_entry = next(
        (
            s
            for s in snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("outcome") == "timeout"
        ),
        None,
    )
    assert timeout_entry is not None
    assert timeout_entry["value"] == 1.0


# ---------------------------------------------------------------------------
# UT-GTM03 — Transport failure increments transport_failures_total
# ---------------------------------------------------------------------------


def test_transport_failure_increments_transport_failures(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """UT-GTM03: Result with transport_class increments transport_failures_total."""
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Connection timeout",
        transport_class=TransportFailureClass.CONNECT_TIMEOUT,
    )
    observe_upstream_attempt("test_provider", result)

    counter = memory_collector._counters.get(TRANSPORT_FAILURES_TOTAL)  # type: ignore[attr-defined]
    assert counter is not None
    snapshot = counter.snapshot()  # type: ignore[attr-defined]

    # Find the entry with provider=test_provider, transport_class=connect_timeout
    failure_entry = next(
        (
            s
            for s in snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("transport_class") == "connect_timeout"
        ),
        None,
    )
    assert failure_entry is not None
    assert failure_entry["value"] == 1.0


# ---------------------------------------------------------------------------
# UT-GTM04 — Success does NOT increment transport_failures_total
# ---------------------------------------------------------------------------


def test_success_does_not_increment_transport_failures(
    memory_collector: MemoryMetricsCollector,
) -> None:
    """UT-GTM04: Successful result does NOT increment transport_failures_total."""
    result = CheckResult.success()
    observe_upstream_attempt("test_provider", result)

    counter = memory_collector._counters.get(TRANSPORT_FAILURES_TOTAL)  # type: ignore[attr-defined]
    # Counter may not exist at all, or may exist with value 0
    if counter is not None:
        snapshot = counter.snapshot()  # type: ignore[attr-defined]
        # No entry should have provider=test_provider
        provider_entries = [
            s for s in snapshot if _labels(s).get("provider") == "test_provider"
        ]
        assert len(provider_entries) == 0


# ---------------------------------------------------------------------------
# UT-GTM05 — Multiple attempts accumulate correctly
# ---------------------------------------------------------------------------


def test_multiple_attempts_accumulate(memory_collector: MemoryMetricsCollector) -> None:
    """UT-GTM05: Multiple calls to observe_upstream_attempt accumulate correctly."""
    # 2 successes
    observe_upstream_attempt("test_provider", CheckResult.success())
    observe_upstream_attempt("test_provider", CheckResult.success())

    # 1 timeout failure
    observe_upstream_attempt(
        "test_provider", CheckResult.fail(ErrorReason.TIMEOUT, "Timeout")
    )

    # 1 transport failure (also counts as attempt)
    observe_upstream_attempt(
        "test_provider",
        CheckResult.fail(
            ErrorReason.NETWORK_ERROR,
            "Connect error",
            transport_class=TransportFailureClass.CONNECT_ERROR,
        ),
    )

    # Check attempts_total
    attempts_counter = memory_collector._counters.get(UPSTREAM_ATTEMPTS_TOTAL)  # type: ignore[attr-defined]
    assert attempts_counter is not None
    attempts_snapshot = attempts_counter.snapshot()  # type: ignore[attr-defined]

    ok_entry = next(
        (
            s
            for s in attempts_snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("outcome") == "ok"
        ),
        None,
    )
    assert ok_entry is not None
    assert ok_entry["value"] == 2.0  # 2 successes

    timeout_entry = next(
        (
            s
            for s in attempts_snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("outcome") == "timeout"
        ),
        None,
    )
    assert timeout_entry is not None
    assert timeout_entry["value"] == 1.0  # 1 timeout

    network_error_entry = next(
        (
            s
            for s in attempts_snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("outcome") == "network_error"
        ),
        None,
    )
    assert network_error_entry is not None
    assert network_error_entry["value"] == 1.0  # 1 network error

    # Check transport_failures_total
    failures_counter = memory_collector._counters.get(TRANSPORT_FAILURES_TOTAL)  # type: ignore[attr-defined]
    assert failures_counter is not None
    failures_snapshot = failures_counter.snapshot()  # type: ignore[attr-defined]

    connect_error_entry = next(
        (
            s
            for s in failures_snapshot
            if _labels(s).get("provider") == "test_provider"
            and _labels(s).get("transport_class") == "connect_error"
        ),
        None,
    )
    assert connect_error_entry is not None
    assert connect_error_entry["value"] == 1.0  # 1 connect_error
