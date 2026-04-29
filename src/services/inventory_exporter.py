# src/services/inventory_exporter.py

"""
Key Inventory Exporter — periodic NDJSON export of API key state.

Implements ``IKeyInventoryExporter`` to query the database for the current
state of every API key and write the results to NDJSON files under
``data/<provider_name>/``.
"""

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

from src.core.atomic_io import write_atomic_ndjson
from src.core.interfaces import IKeyInventoryExporter
from src.core.models import KeyExportSnapshot
from src.db.database import get_pool

if TYPE_CHECKING:
    from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)

_EXPORT_ROOT: str = "data"


class KeyInventoryExporter(IKeyInventoryExporter):
    """Exports current API key state to NDJSON files for backup and monitoring."""

    async def export_snapshot(
        self, provider_name: str, db_manager: "DatabaseManager"
    ) -> None:
        """Export all keys for *provider_name* to ``data/<name>/all_keys.ndjson``."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    ak.id          AS key_id,
                    ak.key_value   AS key_value,
                    kms.model_name AS model_name,
                    kms.status     AS status,
                    kms.next_check_time AS next_check_time
                FROM api_keys ak
                JOIN key_model_status kms ON kms.key_id = ak.id
                JOIN providers p ON p.id = ak.provider_id
                WHERE p.name = $1
                ORDER BY ak.id, kms.model_name
                """,
                provider_name,
            )

        snapshots: list[dict[str, object]] = []
        for row in rows:
            key_value: str = row["key_value"]
            next_check: datetime | None = row["next_check_time"]
            snapshot = KeyExportSnapshot(
                key_id=row["key_id"],
                key_prefix=key_value[:10],
                model_name=row["model_name"],
                status=row["status"],
                next_check_time=(
                    next_check.isoformat() if next_check is not None else ""
                ),
            )
            snapshots.append(snapshot.__dict__)

        path = os.path.join(_EXPORT_ROOT, provider_name, "all_keys.ndjson")
        write_atomic_ndjson(path, snapshots)
        logger.debug(
            "Exported snapshot for '%s': %d records → %s",
            provider_name,
            len(snapshots),
            path,
        )

    async def export_inventory(
        self,
        provider_name: str,
        db_manager: "DatabaseManager",
        statuses: list[str],
    ) -> None:
        """Export keys grouped by status to ``data/<name>/<status>/keys.ndjson``."""
        if not statuses:
            logger.debug(
                "export_inventory for '%s': empty statuses list, nothing to do.",
                provider_name,
            )
            return

        pool = get_pool()
        for status in statuses:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        ak.id          AS key_id,
                        ak.key_value   AS key_value,
                        kms.model_name AS model_name,
                        kms.next_check_time AS next_check_time
                    FROM api_keys ak
                    JOIN key_model_status kms ON kms.key_id = ak.id
                    JOIN providers p ON p.id = ak.provider_id
                    WHERE p.name = $1 AND kms.status = $2
                    ORDER BY ak.id, kms.model_name
                    """,
                    provider_name,
                    status,
                )

            snapshots: list[dict[str, object]] = []
            for row in rows:
                key_value: str = row["key_value"]
                next_check: datetime | None = row["next_check_time"]
                snapshot = KeyExportSnapshot(
                    key_id=row["key_id"],
                    key_prefix=key_value[:10],
                    model_name=row["model_name"],
                    status=status,
                    next_check_time=(
                        next_check.isoformat() if next_check is not None else ""
                    ),
                )
                snapshots.append(snapshot.__dict__)

            path = os.path.join(_EXPORT_ROOT, provider_name, status, "keys.ndjson")
            write_atomic_ndjson(path, snapshots)
            logger.debug(
                "Exported inventory for '%s' [%s]: %d records → %s",
                provider_name,
                status,
                len(snapshots),
                path,
            )
