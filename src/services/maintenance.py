# src/services/maintenance.py

import logging
from src.db import database

# Initialize a logger for this module.
# The output will be handled by the central logging configuration.
logger = logging.getLogger(__name__)

def run_periodic_amnesty(db_path: str):
    """
    Service-level task to grant amnesty to all 'dead' keys.
    This function is intended to be called periodically by the background worker.

    Args:
        db_path: The file path to the SQLite database.
    """
    logger.info("SERVICE: Running periodic task: Amnesty for dead keys.")
    database.amnesty_dead_keys(db_path)

def run_periodic_vacuum(db_path: str):
    """
    Service-level task to perform a VACUUM operation on the database.
    This helps to keep the database file size minimal.
    This function should be called infrequently (e.g., weekly).

    Args:
        db_path: The file path to the SQLite database.
    """
    logger.info("SERVICE: Running periodic task: Database VACUUM.")
    database.vacuum_database(db_path)
