# src/services/maintenance.py

import logging

from src.db.database import DatabaseManager

# Initialize a logger for this module.
# The output will be handled by the central logging configuration.
logger = logging.getLogger(__name__)

# REFACTORED: The run_periodic_amnesty function has been completely removed.
# The new state-aware logic in KeyProbe and the `failing_since` mechanism
# in the database make a separate amnesty service obsolete. The system is
# now self-regulating.


async def run_periodic_vacuum(db_manager: DatabaseManager) -> None:
    """
    Service-level task to perform a VACUUM operation on the database (Async Version).
    In PostgreSQL, this complements the autovacuum daemon and is useful for reclaiming
    storage and preventing transaction ID wraparound in high-throughput environments.
    This function should be called infrequently (e.g., weekly).

    Args:
        db_manager: An instance of the DatabaseManager for async DB access.
    """
    logger.info("SERVICE: Running periodic task: Database VACUUM.")
    try:
        # This function calls the corresponding method on the DatabaseManager facade,
        # keeping the service layer decoupled from the direct database connection logic.
        await db_manager.run_vacuum()
    except Exception as e:
        logger.error(
            "An error occurred during the VACUUM maintenance task.", exc_info=e
        )
