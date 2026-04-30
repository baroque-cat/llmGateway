#!/usr/bin/env python3

"""Key purging service — removes stopped keys and deleted provider data."""

import logging
from datetime import UTC, datetime, timedelta

from src.core.accessor import ConfigAccessor
from src.core.interfaces import IKeyPurger
from src.db.database import DatabaseManager, get_pool
from src.services.db_maintainer import record_purged_keys

logger = logging.getLogger(__name__)


class KeyPurger(IKeyPurger):
    """Implementation of ``IKeyPurger`` for PostgreSQL-backed key cleanup."""

    async def purge_provider(
        self, provider_id: int, db_manager: DatabaseManager
    ) -> int:
        """Delete all key data for a provider removed from configuration.

        Uses ``DELETE ... FROM providers WHERE id = $1``.  ``ON DELETE CASCADE``
        foreign keys automatically remove all rows in ``api_keys`` and
        ``key_model_status``.

        Args:
            provider_id: The database ID of the provider to purge.
            db_manager: The database manager for executing queries.

        Returns:
            The number of API keys that were deleted (via CASCADE).
        """
        pool = get_pool()
        async with pool.acquire() as conn, conn.transaction():
            # Count keys before deletion for the return value.
            key_count = await conn.fetchval(
                "SELECT COUNT(*) FROM api_keys WHERE provider_id = $1",
                provider_id,
            )
            key_count = key_count or 0

            await conn.execute("DELETE FROM providers WHERE id = $1", provider_id)
            logger.info(
                "PURGE: Deleted provider %d with %d keys (CASCADE).",
                provider_id,
                key_count,
            )
            return key_count

    async def purge_stopped_keys(
        self,
        provider_name: str,
        provider_id: int,
        cutoff: datetime,
        db_manager: DatabaseManager,
    ) -> int:
        """Delete keys that have been permanently stopped past *cutoff*.

        A key is eligible when **all** of its ``key_model_status`` rows satisfy:
        - ``failing_since < cutoff`` — has been failing long enough.
        - ``next_check_time > NOW() + INTERVAL '300 days'`` — system has given up
          on re-checking it (stopped state sets ``next_check_time`` 365 days ahead).

        The ``HAVING bool_and(...)`` clause guarantees that only keys where
        *every* model status row meets both conditions are deleted.

        Args:
            provider_name: The unique instance name of the provider.
            provider_id: The database ID of the provider.
            cutoff: Keys with ``failing_since`` before this datetime are
                eligible.
            db_manager: The database manager for executing queries.

        Returns:
            The number of API keys deleted.
        """
        pool = get_pool()
        async with pool.acquire() as conn, conn.transaction():
            result = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM api_keys
                    WHERE provider_id = $1
                      AND id IN (
                          SELECT key_id
                          FROM key_model_status
                          GROUP BY key_id
                          HAVING bool_and(
                              failing_since < $2
                              AND next_check_time > NOW() + INTERVAL '300 days'
                          )
                      )
                    RETURNING id
                )
                SELECT COUNT(*) FROM deleted
                """,
                provider_id,
                cutoff,
            )
            purged_count = result or 0
            if purged_count:
                logger.info(
                    "PURGE '%s': Deleted %d stopped keys (cutoff=%s).",
                    provider_name,
                    purged_count,
                    cutoff.isoformat(),
                )
            record_purged_keys(provider_name, purged_count)
            return purged_count

    @staticmethod
    async def run_scheduled(
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
