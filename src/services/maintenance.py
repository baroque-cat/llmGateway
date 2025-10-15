# src/services/maintenance.py

import logging
from src.db.database import DatabaseManager

# Initialize a logger for this module.
# The output will be handled by the central logging configuration.
logger = logging.getLogger(__name__)

async def run_periodic_amnesty(db_manager: DatabaseManager):
    """
    Service-level task to grant amnesty to all 'dead' keys (Async Version).
    This function is intended to be called periodically by the background worker.

    Args:
        db_manager: An instance of the DatabaseManager for async DB access.
    """
    logger.info("SERVICE: Running periodic task: Amnesty for dead keys.")
    try:
        await db_manager.run_amnesty()
    except Exception as e:
        logger.error("An error occurred during the amnesty maintenance task.", exc_info=e)

async def run_periodic_vacuum(db_manager: DatabaseManager):
    """
    Service-level task to perform a VACUUM operation on the database (Async Version).
    In PostgreSQL, this complements the autovacuum daemon.
    This function should be called infrequently (e.g., weekly).

    Args:
        db_manager: An instance of the DatabaseManager for async DB access.
    """
    logger.info("SERVICE: Running periodic task: Database VACUUM.")
    try:
        await db_manager.run_vacuum()
    except Exception as e:
        logger.error("An error occurred during the VACUUM maintenance task.", exc_info=e)
