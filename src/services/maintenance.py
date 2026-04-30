# src/services/maintenance.py

import logging
from datetime import UTC, datetime, timedelta

from src.core.accessor import ConfigAccessor
from src.db.database import DatabaseManager
from src.services.db_maintainer import DatabaseMaintainer
from src.services.key_purger import KeyPurger

logger = logging.getLogger(__name__)


async def run_purge_stopped_keys(
    accessor: ConfigAccessor, db_manager: DatabaseManager
) -> None:
    """Purge permanently stopped keys for each enabled provider.

    Iterates over all enabled providers and deletes keys that have been in
    a stopped state beyond ``purge.after_days``.  Called weekly by the
    scheduler (Sunday 04:00 UTC).

    Args:
        accessor: Configuration accessor for reading purge policy settings.
        db_manager: Database manager for executing queries.
    """
    purger = KeyPurger()
    now = datetime.now(UTC)

    for provider_name, provider_config in accessor.get_all_providers().items():
        if not provider_config.enabled:
            continue

        health_policy = provider_config.worker_health_policy
        purge_config = health_policy.purge
        cutoff = now - timedelta(days=purge_config.after_days)

        provider_id_map = await db_manager.providers.get_id_map()
        provider_id = provider_id_map.get(provider_name)
        if provider_id is None:
            logger.debug(
                "PURGE SKIP '%s': not found in provider_id_map.", provider_name
            )
            continue

        try:
            deleted = await purger.purge_stopped_keys(
                provider_name=provider_name,
                provider_id=provider_id,
                cutoff=cutoff,
                db_manager=db_manager,
            )
            if deleted:
                logger.info(
                    "PURGE '%s': %d keys purged (cutoff=%s, after_days=%d).",
                    provider_name,
                    deleted,
                    cutoff.isoformat(),
                    purge_config.after_days,
                )
        except Exception as e:
            logger.error(
                "PURGE '%s': failed to purge stopped keys: %s",
                provider_name,
                e,
                exc_info=True,
            )


async def run_conditional_vacuum(
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
