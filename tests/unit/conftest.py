"""Shared fixtures for all unit tests.

Re-exports ``_isolate_metrics_collector`` from
``tests/unit/metrics/conftest.py`` so that tests in
``tests/unit/services/`` and other subdirectories also receive
metrics collector isolation.
"""

from tests.unit.metrics.conftest import _isolate_metrics_collector  # noqa: F401
