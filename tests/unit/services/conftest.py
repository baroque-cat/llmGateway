"""Shared fixtures for keeper-related unit tests.

The ``mock_run_keeper_dependencies`` fixture has been relocated to
``tests/unit/conftest.py`` so that both ``tests/unit/services/`` and
``tests/unit/metrics/`` subtrees have access to it via pytest's
conftest discovery hierarchy.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_observe_upstream_attempt_for_non_metrics_tests(
    request: pytest.FixtureRequest,
) -> None:
    """Patch observe_upstream_attempt to no-op for tests that don't explicitly test metrics.

    The new P0 observability hook calls get_collector().counter() which can cause
    Prometheus registry collisions when tests run together. Tests that explicitly
    test metrics (e.g. test_gateway_transport_metrics.py) should NOT use this fixture.
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
