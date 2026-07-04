# metrics-fixture-dedup

## Purpose

Shared autouse fixture (`_isolate_metrics_collector`) using
`monkeypatch.delenv()` for pytest-native metrics collector isolation across
unit and integration tests, replacing 4 duplicated inline fixtures with
`os.environ.pop()` workarounds.

## Requirements

### Requirement: Metrics collector is isolated between tests via shared autouse fixture

The project SHALL provide a shared `_isolate_metrics_collector` autouse fixture
in `tests/unit/metrics/conftest.py` that resets the metrics collector singleton
before and after each test using `monkeypatch.delenv()` for pytest-native
environment isolation.

#### Scenario: Shared fixture resets collector singleton before and after each test

- **WHEN** any test in `tests/unit/metrics/` or `tests/unit/` subdirectories runs
- **THEN** the `_isolate_metrics_collector` autouse fixture SHALL call `reset_collector()` before the test
- **AND** the fixture SHALL call `monkeypatch.delenv("METRICS_BACKEND", raising=False)`
- **AND** the fixture SHALL call `monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)`
- **AND** the fixture SHALL repeat the same reset sequence after the test (in the `yield` cleanup phase)

#### Scenario: Shared fixture covers all metrics unit test files

- **WHEN** `tests/unit/metrics/conftest.py` exists with the shared fixture
- **THEN** files in `tests/unit/metrics/` SHALL NOT define their own duplicate metrics isolation fixtures
- **AND** `tests/unit/conftest.py` SHALL re-export the fixture so that `tests/unit/services/test_keeper_metrics.py` is also covered

#### Scenario: Integration tests have their own isolation fixture

- **WHEN** integration tests under `tests/integration/` run
- **THEN** the existing `tests/integration/conftest.py` SHALL provide an equivalent `_isolate_metrics_collector` fixture
- **AND** `tests/integration/test_keeper_metrics_endpoint.py` SHALL NOT define its own duplicate inline fixture

### Requirement: Prometheus backend tests use shared fixture instead of workarounds

The project SHALL update `tests/unit/metrics/test_prometheus_backend.py` to
rely on the shared `_isolate_metrics_collector` fixture from
`tests/unit/metrics/conftest.py` instead of the `_make_unique_name()` counter
and `PrometheusMetricsCollector.__new__()` hacks, except where those hacks are
needed for tests that intentionally exercise REGISTRY collision scenarios.

#### Scenario: Prometheus tests no longer depend on _make_unique_name

- **WHEN** `test_prometheus_backend.py` tests run with the shared isolation fixture
- **THEN** metric name collisions SHALL NOT occur between test functions
- **AND** the `_make_unique_name()` counter SHALL be removed or restricted to REGISTRY-specific tests
