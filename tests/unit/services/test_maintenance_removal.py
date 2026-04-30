#!/usr/bin/env python3

"""Tests for maintenance module removal verification — N52.

Verifies that ``run_periodic_vacuum`` has been removed from the
maintenance module, while ``run_purge_stopped_keys`` and
``run_conditional_vacuum`` remain.
"""

from src.services import maintenance


def test_run_periodic_vacuum_removed_from_maintenance_module() -> None:
    """N52: ``run_periodic_vacuum`` no longer exists in the maintenance module."""
    assert (
        hasattr(maintenance, "run_periodic_vacuum") is False
    ), "run_periodic_vacuum should have been removed from the maintenance module"


def test_run_purge_stopped_keys_exists_in_maintenance_module() -> None:
    """N52 (supplementary): ``run_purge_stopped_keys`` still exists."""
    assert (
        hasattr(maintenance, "run_purge_stopped_keys") is True
    ), "run_purge_stopped_keys must exist in the maintenance module"


def test_run_conditional_vacuum_exists_in_maintenance_module() -> None:
    """N52 (supplementary): ``run_conditional_vacuum`` still exists."""
    assert (
        hasattr(maintenance, "run_conditional_vacuum") is True
    ), "run_conditional_vacuum must exist in the maintenance module"
