# src/services/maintenance.py

from src.db import database

def run_periodic_amnesty(db_path: str):
    """
    Service-level task to grant amnesty to all 'dead' keys.
    This function is intended to be called periodically by the background worker.

    Args:
        db_path: The file path to the SQLite database.
    """
    print("SERVICE: Running periodic task: Amnesty for dead keys.")
    database.amnesty_dead_keys(db_path)

def run_periodic_vacuum(db_path: str):
    """
    Service-level task to perform a VACUUM operation on the database.
    This helps to keep the database file size minimal.
    This function should be called infrequently (e.g., weekly).

    Args:
        db_path: The file path to the SQLite database.
    """
    print("SERVICE: Running periodic task: Database VACUUM.")
    database.vacuum_database(db_path)

