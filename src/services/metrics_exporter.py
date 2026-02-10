"""
Prometheus metrics exporter service for the LLM Gateway.

This module provides a service to collect and format key status metrics
from the database in a format compatible with Prometheus.
"""

import logging
from datetime import UTC, datetime

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.core import REGISTRY, GaugeMetricFamily

from src.db.database import DatabaseManager, StatusSummaryItem

logger = logging.getLogger(__name__)


class KeyStatusCollector:
    """
    A custom collector for Prometheus that gathers key status metrics from the database.

    This class implements the Collector interface expected by Prometheus client.
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize the collector.

        Args:
            db_manager: Database manager instance for querying key status data
        """
        self.db_manager = db_manager
        self._cached_metrics = []
        self._last_update = None

    def collect(self):
        """
        Collects metrics from the database and yields them as GaugeMetricFamily objects.

        This method is called by the Prometheus client library when scraping metrics.
        """
        try:
            # Since this is called from a sync context (Prometheus client), we cannot
            # directly await async database calls. Instead, we use a cached approach.
            # The cache should be updated periodically by an async task.
            if not self._cached_metrics:
                # If no cache, return empty metrics to avoid blocking
                logger.warning("No cached metrics available for Prometheus collection")
                key_status_gauge = GaugeMetricFamily(
                    "llm_gateway_keys_total",
                    "Total number of API keys by provider, model, and status",
                    labels=["provider", "model", "status"],
                )
                yield key_status_gauge
                return

            # Create a gauge metric family for key counts
            key_status_gauge = GaugeMetricFamily(
                "llm_gateway_keys_total",
                "Total number of API keys by provider, model, and status",
                labels=["provider", "model", "status"],
            )

            # Add each record to the gauge
            for record in self._cached_metrics:
                # Handle shared key status - replace __ALL_MODELS__ with 'shared' for better UX
                model_name = record["model"]
                if model_name == "__ALL_MODELS__":
                    model_name = "shared"

                key_status_gauge.add_metric(
                    [record["provider"], model_name, record["status"]],
                    record["count"],
                )

            yield key_status_gauge

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}", exc_info=True)
            # We don't re-raise here because Prometheus should still get other metrics

    def update_cache(self, metrics_data: list[StatusSummaryItem]):
        """
        Update the cached metrics data from an async context.

        Args:
            metrics_data: List of metric records from the database
        """
        self._cached_metrics = metrics_data
        self._last_update = datetime.now(UTC)


class MetricsService:
    """
    Service for managing Prometheus metrics collection.

    This service registers the custom collector with the Prometheus client registry.
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize the metrics service.

        Args:
            db_manager: Database manager instance for querying key status data
        """
        self.db_manager = db_manager
        self.collector = KeyStatusCollector(db_manager)
        # Check if the collector is already registered to avoid duplicates
        try:
            REGISTRY.register(self.collector)
        except ValueError as e:
            # Handle duplicate registration gracefully
            error_msg = str(e).lower()
            if "duplicate" in error_msg or "duplicated" in error_msg:
                logger.warning(
                    "Metrics collector already registered, skipping registration"
                )
            else:
                logger.error(f"Error registering metrics collector: {e}", exc_info=True)
                raise
        except Exception as e:
            logger.error(f"Error registering metrics collector: {e}", exc_info=True)
            raise

    def get_metrics(self) -> tuple[bytes, str]:
        """
        Get metrics in Prometheus format.

        Returns:
            Tuple of (metrics_data, content_type)
        """
        metrics_data = generate_latest(REGISTRY)
        return metrics_data, CONTENT_TYPE_LATEST

    async def update_metrics_cache(self):
        """
        Update the metrics cache by fetching fresh data from the database.

        This method should be called periodically from an async context.
        """
        try:
            summary_data = await self.db_manager.keys.get_status_summary()
            self.collector.update_cache(summary_data)
        except Exception as e:
            logger.error(f"Error updating metrics cache: {e}", exc_info=True)
