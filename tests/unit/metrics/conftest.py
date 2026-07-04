"""Shared fixtures for metrics unit tests.

Provides the ``_isolate_metrics_collector`` autouse fixture that resets
the metrics collector singleton and deletes relevant environment
variables before and after each test using ``monkeypatch.delenv()``
for pytest-native environment isolation.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from src.metrics import reset_collector


@pytest.fixture(autouse=True)
def _isolate_metrics_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Reset the collector singleton and clean env vars before and after each test.

    Uses ``monkeypatch.delenv()`` for pytest-native environment isolation
    that auto-restores values after the test completes.
    """
    reset_collector()
    monkeypatch.delenv("METRICS_BACKEND", raising=False)
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    yield
    reset_collector()
    monkeypatch.delenv("METRICS_BACKEND", raising=False)
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
