#!/usr/bin/env python3

"""Unit tests for DatabaseManager method removal verification — test N53.

Verifies that run_vacuum has been removed from DatabaseManager and that
get_table_health is present.
"""

from src.db.database import DatabaseManager


def test_database_manager_run_vacuum_removed():
    """N53: DatabaseManager no longer has a run_vacuum method."""
    assert hasattr(DatabaseManager, "run_vacuum") is False


def test_database_manager_has_get_table_health():
    """Verify that DatabaseManager still has get_table_health method."""
    assert hasattr(DatabaseManager, "get_table_health") is True
