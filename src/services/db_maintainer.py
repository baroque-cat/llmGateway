#!/usr/bin/env python3

"""Database maintenance service — conditional VACUUM ANALYZE based on metrics."""

import logging

from src.core.accessor import ConfigAccessor
from src.core.interfaces import IDatabaseMaintainer
from src.core.models import DatabaseTableHealth
from src.core.policy_utils import should_vacuum
from src.db.database import DatabaseManager, get_pool
from src.metrics import get_collector
from src.metrics.registry import (
    DB_DEAD_RATIO,
    DB_DEAD_TUPLES,
    DB_PURGED_KEYS,
    DB_VACUUM_COUNT,
)

logger = logging.getLogger(__name__)


def _db_maintainer_collector():
    """Lazy collector accessor for the metrics."""
    return get_collector()


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

        collector = _db_maintainer_collector()
        dead_tuples_gauge = collector.gauge(
            DB_DEAD_TUPLES,
            "Number of dead tuples per user table",
            ["table"],
        )
        dead_ratio_gauge = collector.gauge(
            DB_DEAD_RATIO,
            "Dead tuple ratio per user table",
            ["table"],
        )
        vacuum_counter = collector.counter(
            DB_VACUUM_COUNT,
            "Total number of VACUUM ANALYZE operations per table",
            ["table"],
        )

        vacuumed = 0
        pool = get_pool()

        for health in tables:
            # Update gauges with current state.
            dead_tuples_gauge.set(
                float(health.n_dead_tup), {"table": health.table_name}
            )
            dead_ratio_gauge.set(health.dead_tuple_ratio, {"table": health.table_name})

            if should_vacuum(health, threshold):
                async with pool.acquire() as conn:
                    # VACUUM ANALYZE must run outside a transaction block.
                    await conn.execute(f'VACUUM ANALYZE "{health.table_name}"')
                vacuum_counter.inc(labels={"table": health.table_name})
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

    @staticmethod
    async def run_scheduled(
        accessor: ConfigAccessor, db_manager: DatabaseManager
    ) -> None:
        """Check table health and conditionally run ``VACUUM ANALYZE``.

        Queries ``pg_stat_user_tables`` for dead tuple statistics and vacuums
        tables whose dead ratio exceeds the configured threshold.  Called by
        the scheduler every ``vacuum_policy.interval_minutes``.

        Args:
            accessor: Configuration accessor for reading vacuum policy settings.
            db_manager: Database manager for executing queries.
        """
        maintainer = DatabaseMaintainer()
        db_config = accessor.get_database_config()
        vacuum_policy = db_config.vacuum_policy

        tables = await maintainer.get_table_health(db_manager)
        await maintainer.run_conditional_vacuum(
            tables=tables,
            db_manager=db_manager,
            threshold=vacuum_policy.dead_tuple_ratio_threshold,
        )


def record_purged_keys(provider_name: str, count: int) -> None:
    """Record purged key count in Prometheus counter.

    Args:
        provider_name: The unique instance name of the provider.
        count: Number of keys purged.
    """
    if count > 0:
        collector = _db_maintainer_collector()
        purged_counter = collector.counter(
            DB_PURGED_KEYS,
            "Total number of API keys purged per provider",
            ["provider"],
        )
        purged_counter.inc(float(count), {"provider": provider_name})
