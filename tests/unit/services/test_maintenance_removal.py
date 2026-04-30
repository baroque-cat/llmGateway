"""Tests verifying maintenance.py deletion and absorption into service classes."""

import importlib

import pytest


class TestMaintenanceModuleRemoval:
    """Verify the maintenance module no longer exists."""

    def test_maintenance_module_import_fails(self) -> None:
        """Importing src.services.maintenance should raise ImportError."""
        with pytest.raises(ImportError):
            importlib.import_module("src.services.maintenance")


class TestKeyPurgerRunScheduled:
    """Verify KeyPurger.run_scheduled exists as a static method."""

    def test_run_scheduled_is_static_method(self) -> None:
        """KeyPurger.run_scheduled should be a static method."""
        from src.services.key_purger import KeyPurger

        assert hasattr(
            KeyPurger, "run_scheduled"
        ), "KeyPurger.run_scheduled should exist"
        # getattr unwraps staticmethod descriptors, so check __dict__ directly
        method = KeyPurger.__dict__["run_scheduled"]
        assert isinstance(
            method, staticmethod
        ), "KeyPurger.run_scheduled should be a static method"


class TestDatabaseMaintainerRunScheduled:
    """Verify DatabaseMaintainer.run_scheduled exists as a static method."""

    def test_run_scheduled_is_static_method(self) -> None:
        """DatabaseMaintainer.run_scheduled should be a static method."""
        from src.services.db_maintainer import DatabaseMaintainer

        assert hasattr(
            DatabaseMaintainer, "run_scheduled"
        ), "DatabaseMaintainer.run_scheduled should exist"
        # getattr unwraps staticmethod descriptors, so check __dict__ directly
        method = DatabaseMaintainer.__dict__["run_scheduled"]
        assert isinstance(
            method, staticmethod
        ), "DatabaseMaintainer.run_scheduled should be a static method"
