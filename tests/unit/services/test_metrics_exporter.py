#!/usr/bin/env python3

"""
Unit tests for Prometheus metrics exporter service.

This module tests the KeyStatusCollector and MetricsService classes.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY
from prometheus_client.core import GaugeMetricFamily

from src.db.database import DatabaseManager
from src.services.metrics_exporter import KeyStatusCollector, MetricsService


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    manager = MagicMock(spec=DatabaseManager)
    manager.keys = MagicMock()
    return manager


@pytest.fixture
def mock_status_summary_items():
    """Sample status summary data for tests."""
    return [
        {"provider": "openai", "model": "gpt-4", "status": "valid", "count": 5},
        {
            "provider": "openai",
            "model": "gpt-3.5-turbo",
            "status": "invalid",
            "count": 2,
        },
        {"provider": "anthropic", "model": "claude-3", "status": "valid", "count": 3},
        {
            "provider": "anthropic",
            "model": "claude-2",
            "status": "untested",
            "count": 1,
        },
    ]


class TestKeyStatusCollector:
    """Test KeyStatusCollector class."""

    def test_init(self, mock_db_manager):
        """Test collector initialization."""
        collector = KeyStatusCollector(mock_db_manager)
        assert collector.db_manager == mock_db_manager
        assert collector._cached_metrics == []
        assert collector._last_update is None

    def test_update_cache(self, mock_db_manager):
        """Test updating cache with metrics data."""
        collector = KeyStatusCollector(mock_db_manager)
        metrics_data = [
            {"provider": "test", "model": "model1", "status": "valid", "count": 10}
        ]

        collector.update_cache(metrics_data)

        assert collector._cached_metrics == metrics_data
        assert collector._last_update is not None
        assert isinstance(collector._last_update, datetime)

    def test_collect_with_empty_cache(self, mock_db_manager):
        """Test collect() when cache is empty returns empty gauge."""
        collector = KeyStatusCollector(mock_db_manager)
        collector._cached_metrics = []

        metrics = list(collector.collect())

        assert len(metrics) == 1
        gauge = metrics[0]
        assert isinstance(gauge, GaugeMetricFamily)
        assert gauge.name == "llm_gateway_keys_total"
        assert (
            gauge.documentation
            == "Total number of API keys by provider, model, and status"
        )
        assert gauge.type == "gauge"
        assert gauge.samples == []  # No samples added

    def test_collect_with_cached_data(self, mock_db_manager, mock_status_summary_items):
        """Test collect() with cached metrics data."""
        collector = KeyStatusCollector(mock_db_manager)
        collector.update_cache(mock_status_summary_items)

        metrics = list(collector.collect())

        assert len(metrics) == 1
        gauge = metrics[0]
        assert isinstance(gauge, GaugeMetricFamily)
        assert gauge.name == "llm_gateway_keys_total"

        # Check samples
        samples = gauge.samples
        assert len(samples) == len(mock_status_summary_items)

        # Verify each sample
        for i, item in enumerate(mock_status_summary_items):
            sample = samples[i]
            assert sample.name == "llm_gateway_keys_total"
            assert sample.value == item["count"]
            assert sample.labels["provider"] == item["provider"]
            assert sample.labels["model"] == item["model"]
            assert sample.labels["status"] == item["status"]

    def test_collect_exception_handling(self, mock_db_manager):
        """Test collect() handles exceptions gracefully."""
        collector = KeyStatusCollector(mock_db_manager)

        # Simulate an exception during collection
        with (
            patch.object(
                GaugeMetricFamily, "__init__", side_effect=Exception("Test error")
            ),
            patch("src.services.metrics_exporter.logger") as mock_logger,
        ):
            list(collector.collect())  # Should not raise

            # Should log error but not raise
            mock_logger.error.assert_called_once()

    def test_collect_with_none_cache(self, mock_db_manager):
        """Test collect() when _cached_metrics is None (edge case)."""
        collector = KeyStatusCollector(mock_db_manager)
        collector._cached_metrics = None  # Simulate unexpected state

        # This should not crash
        metrics = list(collector.collect())
        # Should handle gracefully and return empty gauge
        assert len(metrics) == 1
        gauge = metrics[0]
        assert gauge.name == "llm_gateway_keys_total"


class TestMetricsService:
    """Test MetricsService class."""

    def test_init_registers_collector(self, mock_db_manager):
        """Test service initialization registers collector with Prometheus registry."""
        # Mock REGISTRY.register to verify it's called
        with patch("src.services.metrics_exporter.REGISTRY.register") as mock_register:
            service = MetricsService(mock_db_manager)

            assert service.db_manager == mock_db_manager
            assert isinstance(service.collector, KeyStatusCollector)
            assert service.collector.db_manager == mock_db_manager

            # Collector should be registered
            mock_register.assert_called_once_with(service.collector)

    def test_init_handles_duplicate_registration(self, mock_db_manager):
        """Test duplicate collector registration is handled gracefully."""
        # First registration
        _service1 = MetricsService(mock_db_manager)

        # Mock REGISTRY.register to raise ValueError with "duplicate"
        with patch("src.services.metrics_exporter.REGISTRY.register") as mock_register:
            mock_register.side_effect = ValueError(
                "Collector already registered (duplicate)"
            )

            with patch("src.services.metrics_exporter.logger") as mock_logger:
                # Should not raise
                service2 = MetricsService(mock_db_manager)

                # Should log warning
                mock_logger.warning.assert_called_once_with(
                    "Metrics collector already registered, skipping registration"
                )

                # Service should still be created
                assert service2.db_manager == mock_db_manager
                assert isinstance(service2.collector, KeyStatusCollector)

    def test_init_handles_other_value_error(self, mock_db_manager):
        """Test other ValueError during registration is re-raised."""
        with patch("src.services.metrics_exporter.REGISTRY.register") as mock_register:
            mock_register.side_effect = ValueError("Some other error")

            with patch("src.services.metrics_exporter.logger") as mock_logger:
                with pytest.raises(ValueError, match="Some other error"):
                    MetricsService(mock_db_manager)

                # Should log error
                mock_logger.error.assert_called_once()

    def test_init_handles_general_exception(self, mock_db_manager):
        """Test general exception during registration is re-raised."""
        with patch("src.services.metrics_exporter.REGISTRY.register") as mock_register:
            mock_register.side_effect = RuntimeError("Registry locked")

            with patch("src.services.metrics_exporter.logger") as mock_logger:
                with pytest.raises(RuntimeError, match="Registry locked"):
                    MetricsService(mock_db_manager)

                # Should log error
                mock_logger.error.assert_called_once()

    def test_get_metrics(self, mock_db_manager):
        """Test get_metrics() returns proper format."""
        service = MetricsService(mock_db_manager)

        # Mock generate_latest to return test data
        test_metrics = b"test_metrics_data"
        with patch("src.services.metrics_exporter.generate_latest") as mock_generate:
            mock_generate.return_value = test_metrics

            metrics_data, content_type = service.get_metrics()

            mock_generate.assert_called_once_with(REGISTRY)
            assert metrics_data == test_metrics
            assert content_type == CONTENT_TYPE_LATEST

    @pytest.mark.asyncio
    async def test_update_metrics_cache_success(
        self, mock_db_manager, mock_status_summary_items
    ):
        """Test update_metrics_cache() successfully updates collector cache."""
        service = MetricsService(mock_db_manager)

        # Mock database call
        mock_db_manager.keys.get_status_summary = AsyncMock(
            return_value=mock_status_summary_items
        )

        await service.update_metrics_cache()

        # Verify database was called
        mock_db_manager.keys.get_status_summary.assert_called_once()

        # Verify cache was updated
        assert service.collector._cached_metrics == mock_status_summary_items
        assert service.collector._last_update is not None

    @pytest.mark.asyncio
    async def test_update_metrics_cache_database_error(self, mock_db_manager):
        """Test update_metrics_cache() handles database errors gracefully."""
        service = MetricsService(mock_db_manager)

        # Mock database call to raise exception
        mock_db_manager.keys.get_status_summary = AsyncMock(
            side_effect=Exception("DB error")
        )

        with patch("src.services.metrics_exporter.logger") as mock_logger:
            # Should not raise
            await service.update_metrics_cache()

            # Should log error
            mock_logger.error.assert_called_once()

            # Cache should remain unchanged (empty)
            assert service.collector._cached_metrics == []
            assert service.collector._last_update is None

    @pytest.mark.asyncio
    async def test_update_metrics_cache_with_existing_cache(self, mock_db_manager):
        """Test update_metrics_cache() overwrites existing cache."""
        service = MetricsService(mock_db_manager)

        # Set existing cache
        old_data = [{"provider": "old", "model": "old", "status": "valid", "count": 1}]
        service.collector.update_cache(old_data)
        old_timestamp = service.collector._last_update

        # Mock new data
        new_data = [{"provider": "new", "model": "new", "status": "valid", "count": 2}]
        mock_db_manager.keys.get_status_summary = AsyncMock(return_value=new_data)

        await service.update_metrics_cache()

        # Verify cache updated
        assert service.collector._cached_metrics == new_data
        assert service.collector._last_update != old_timestamp
        assert service.collector._last_update > old_timestamp
