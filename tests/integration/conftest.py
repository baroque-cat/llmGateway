"""Shared fixtures for integration tests.

Provides the ``_isolate_metrics_collector`` autouse fixture for metrics isolation.
Helper functions ``make_mock_request`` and ``create_mock_provider_config`` have
been extracted to ``tests/integration/_helpers.py`` — import them explicitly:

    from tests.integration._helpers import make_mock_request, create_mock_provider_config
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

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


@pytest.fixture(autouse=True)
def _patch_observe_upstream_attempt_for_non_metrics_tests(
    request: pytest.FixtureRequest,
) -> Generator[None]:
    """Patch observe_upstream_attempt to no-op for tests that don't explicitly test metrics.

    The new P0 observability hook calls get_collector().counter() which can cause
    Prometheus registry collisions when tests run together. Tests that explicitly
    test metrics should NOT use this fixture.
    """
    # Skip patching for tests that explicitly test metrics
    test_module = request.module.__name__
    if "metrics" in test_module.lower():
        yield
        return

    with patch(
        "src.services.gateway.gateway_service.observe_upstream_attempt",
        new=MagicMock(),
    ):
        yield
