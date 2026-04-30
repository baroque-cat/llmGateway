#!/usr/bin/env python3

"""Database maintenance service — conditional VACUUM ANALYZE based on metrics."""

import logging

from prometheus_client import Counter, Gauge

from src.core.interfaces import IDatabaseMaintainer
from src.core.models import DatabaseTableHealth
from src.core.policy_utils import should_vacuum
from src.db.database import DatabaseManager, get_pool

logger = logging.getLogger(__name__)

# --- Prometheus metrics for database health and vacuum operations ---

# Gauge — dead tuple count per table
_db_dead_tuples_gauge = Gauge(
    "llm_gateway_db_dead_tuples",
    "Number of dead tuples per user table",
    labelnames=["table"],
)

# Gauge — dead tuple ratio per table
_db_dead_ratio_gauge = Gauge(
    "llm_gateway_db_dead_ratio",
    "Dead tuple ratio per user table",
    labelnames=["table"],
)

# Counter — vacuum operations per table
_db_vacuum_count_counter = Counter(
    "llm_gateway_db_vacuum_count",
    "Total number of VACUUM ANALYZE operations per table",
    labelnames=["table"],
)

# Counter — purged keys per provider
_purged_keys_total_counter = Counter(
    "llm_gateway_purged_keys_total",
    "Total number of API keys purged per provider",
    labelnames=["provider"],
)


class DatabaseMaintainer(IDatabaseMaintainer):
    """Implementation of ``IDatabaseMaintainer`` using ``pg_stat_user_tables``.

    Periodically queries table health statistics and conditionally runs
    ``VACUUM ANALYZE`` on tables whose dead-tuple ratio exceeds a
    configured threshold.
    """

    async def get_table_health(
        self, db_manager: DatabaseManager
    ) -> list[DatabaseTableHealth]:
        """Delegates to ``DatabaseManager.get_table_health()``."""
        return await db_manager.get_table_health()

    async def run_conditional_vacuum(
        self,
        tables: list[DatabaseTableHealth],
        db_manager: DatabaseManager,
        threshold: float = 0.3,
    ) -> int:
        """Run ``VACUUM ANALYZE`` on tables that exceed the dead tuple threshold.

        Iterates over *tables*, updates Prometheus gauges for each table,
        and issues ``VACUUM ANALYZE <table_name>`` for tables whose
        ``dead_tuple_ratio`` exceeds *threshold* and whose ``n_dead_tup``
        is above the 100-row guard.

        Args:
            tables: Health records from ``get_table_health()``.
            db_manager: The database manager (unused; pool obtained
                directly for VACUUM — the parameter satisfies the
                interface contract).
            threshold: Dead tuple ratio above which vacuum is triggered.

        Returns:
            The number of tables that were vacuumed.
        """
        if not tables:
            logger.warning(
                "Smart VACUUM: No table health data available (pg_stat_user_tables "
                "may be inaccessible). Skipping VACUUM cycle."
            )
            return 0

        vacuumed = 0
        pool = get_pool()

        for health in tables:
            # Update Prometheus gauges with current state.
            _db_dead_tuples_gauge.labels(table=health.table_name).set(health.n_dead_tup)
            _db_dead_ratio_gauge.labels(table=health.table_name).set(
                health.dead_tuple_ratio
            )

            if should_vacuum(health, threshold):
                async with pool.acquire() as conn:
                    # VACUUM ANALYZE must run outside a transaction block.
                    await conn.execute(f'VACUUM ANALYZE "{health.table_name}"')
                _db_vacuum_count_counter.labels(table=health.table_name).inc()
                vacuumed += 1
                logger.info(
                    "Smart VACUUM: VACUUM ANALYZE on '%s' (dead=%.2f%%, " "n_dead=%d).",
                    health.table_name,
                    health.dead_tuple_ratio * 100,
                    health.n_dead_tup,
                )

        if vacuumed:
            logger.info("Smart VACUUM: %d table(s) vacuumed.", vacuumed)
        return vacuumed


def record_purged_keys(provider_name: str, count: int) -> None:
    """Record purged key count in Prometheus counter.

    Args:
        provider_name: The unique instance name of the provider.
        count: Number of keys purged.
    """
    if count > 0:
        _purged_keys_total_counter.labels(provider=provider_name).inc(count)
