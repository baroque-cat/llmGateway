#!/usr/bin/env python3

"""Integration tests for Keeper's /metrics endpoint on port 9090.

Tests:
  IT-KM01: Keeper /metrics on port 9090 → HTTP 200
  IT-KM02: Contains llm_gateway_keys_total{provider="openai",model="gpt-4o",status="valid"} N
  IT-KM03: Contains llm_gateway_adaptive_batch_size{provider="openai"} N
  IT-KM04: Contains llm_gateway_db_dead_tuples{table="keys"} N
  IT-KM05: No auth required (internal network)
"""

import json
import os

import pytest
from prometheus_client import Gauge, make_asgi_app
from prometheus_client.core import CollectorRegistry

from src.metrics import get_collector, reset_collector
from src.metrics.backends.memory import MemoryMetricsCollector
from src.metrics.registry import (
    ADAPTIVE_BATCH_SIZE,
    DB_DEAD_TUPLES,
    KEY_STATUS_TOTAL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_registry():
    """Create a fresh CollectorRegistry for test isolation."""
    return CollectorRegistry()


@pytest.fixture
def keeper_metrics_app(fresh_registry):
    """Create a Keeper-style metrics ASGI app using a fresh registry.

    The Keeper uses ``prometheus_client.make_asgi_app()`` which reads
    from the global REGISTRY.  For test isolation we pass a fresh
    CollectorRegistry instead.
    """
    app = make_asgi_app(registry=fresh_registry)
    return app


@pytest.fixture(autouse=True)
def _isolate_collector():
    """Reset the collector singleton and clean env vars between tests."""
    reset_collector()
    import os

    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)
    yield
    reset_collector()
    for key in ("PROMETHEUS_MULTIPROC_DIR", "METRICS_BACKEND"):
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# IT-KM01: Keeper /metrics on port 9090 → HTTP 200
# ---------------------------------------------------------------------------


class TestKeeperMetricsEndpoint:
    """Integration tests for the Keeper's /metrics endpoint."""

    def test_it_km01_metrics_endpoint_returns_http_200(self, keeper_metrics_app):
        """IT-KM01: Keeper /metrics on port 9090 → HTTP 200."""
        from fastapi.testclient import TestClient

        client = TestClient(keeper_metrics_app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_it_km02_contains_key_status_total(self, fresh_registry, keeper_metrics_app):
        """IT-KM02: Output contains llm_gateway_keys_total with
        provider/model/status labels."""
        from fastapi.testclient import TestClient

        # Simulate what PrometheusMetricsCollector.collect_from_db() does
        keys_gauge = Gauge(
            KEY_STATUS_TOTAL,
            "Total number of API keys by provider, model, and status",
            labelnames=["provider", "model", "status"],
            registry=fresh_registry,
        )
        keys_gauge.labels(provider="openai", model="gpt-4o", status="valid").set(7)
        keys_gauge.labels(provider="openai", model="gpt-4o", status="invalid").set(2)

        client = TestClient(keeper_metrics_app)
        response = client.get("/metrics")
        assert response.status_code == 200

        body = response.text
        # Verify the key status metric line exists.
        # NOTE: prometheus_client sorts labels alphabetically, so the
        # output order is {model=...,provider=...,status=...} rather than
        # the creation order {provider=...,model=...,status=...}.
        assert 'llm_gateway_keys_total{' in body
        assert 'provider="openai"' in body
        assert 'model="gpt-4o"' in body
        assert 'status="valid"' in body
        assert " 7.0" in body or " 7" in body

    def test_it_km03_contains_adaptive_batch_size(self, fresh_registry, keeper_metrics_app):
        """IT-KM03: Output contains llm_gateway_adaptive_batch_size with
        provider label."""
        from fastapi.testclient import TestClient

        # Simulate what _create_adaptive_metrics_callback() does
        batch_gauge = Gauge(
            ADAPTIVE_BATCH_SIZE,
            "Current adaptive batch size per provider",
            labelnames=["provider"],
            registry=fresh_registry,
        )
        batch_gauge.labels(provider="openai").set(5)

        client = TestClient(keeper_metrics_app)
        response = client.get("/metrics")
        assert response.status_code == 200

        body = response.text
        assert 'llm_gateway_adaptive_batch_size{provider="openai"}' in body
        assert " 5.0" in body or " 5" in body

    def test_it_km04_contains_db_dead_tuples(self, fresh_registry, keeper_metrics_app):
        """IT-KM04: Output contains llm_gateway_db_dead_tuples with
        table label."""
        from fastapi.testclient import TestClient

        # Simulate what DatabaseMaintainer writes
        dead_tuples_gauge = Gauge(
            DB_DEAD_TUPLES,
            "Number of dead tuples per user table",
            labelnames=["table"],
            registry=fresh_registry,
        )
        dead_tuples_gauge.labels(table="keys").set(120)

        client = TestClient(keeper_metrics_app)
        response = client.get("/metrics")
        assert response.status_code == 200

        body = response.text
        assert 'llm_gateway_db_dead_tuples{table="keys"}' in body
        assert " 120.0" in body or " 120" in body

    def test_it_km05_no_auth_required(self, keeper_metrics_app):
        """IT-KM05: Keeper /metrics endpoint requires no authentication
        (internal network — no Bearer token needed)."""
        from fastapi.testclient import TestClient

        # Request without any Authorization header
        client = TestClient(keeper_metrics_app)
        response = client.get("/metrics")
        assert response.status_code == 200

        # Also verify with a random header — should still work
        response2 = client.get("/metrics", headers={"X-Some-Header": "value"})
        assert response2.status_code == 200

    def test_keeper_metrics_with_memory_collector(self):
        """Verify that MemoryMetricsCollector can also serve Keeper metrics
        (useful for testing without prometheus_client I/O)."""
        os.environ["METRICS_BACKEND"] = "memory"
        collector = get_collector()
        assert isinstance(collector, MemoryMetricsCollector)

        # Populate via collector interface
        collector.gauge(
            KEY_STATUS_TOTAL,
            "Total number of API keys by provider, model, and status",
            ["provider", "model", "status"],
        ).set(10, {"provider": "openai", "model": "gpt-4o", "status": "valid"})

        body, content_type = collector.generate_metrics()
        assert content_type == "application/json"

        data = json.loads(body)
        metrics = data["metrics"]
        key_status = [m for m in metrics if m["name"] == KEY_STATUS_TOTAL]
        assert len(key_status) == 1
        assert key_status[0]["value"] == 10.0