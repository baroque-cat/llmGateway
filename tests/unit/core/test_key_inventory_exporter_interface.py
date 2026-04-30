#!/usr/bin/env python3

"""Tests for IKeyInventoryExporter ABC — Group 4: Core interface contract.

Verifies that IKeyInventoryExporter is a proper ABC with two abstract
methods, cannot be instantiated without implementations, and has correct
signatures.
"""

import inspect
from abc import ABC

import pytest

from src.core.interfaces import IKeyInventoryExporter

# ---------------------------------------------------------------------------
# 4.1  IKeyInventoryExporter inherits ABC
# ---------------------------------------------------------------------------


def test_ikey_inventory_exporter_is_abc() -> None:
    """IKeyInventoryExporter is a subclass of ABC."""
    assert issubclass(
        IKeyInventoryExporter, ABC
    ), "IKeyInventoryExporter should inherit from ABC"


# ---------------------------------------------------------------------------
# 4.2  export_snapshot is an abstract method
# ---------------------------------------------------------------------------


def test_export_snapshot_is_abstract_method() -> None:
    """export_snapshot is decorated with @abstractmethod."""
    method = IKeyInventoryExporter.export_snapshot
    # The __isabstractmethod__ attribute is set by the @abstractmethod decorator.
    assert getattr(
        method, "__isabstractmethod__", False
    ), "export_snapshot should be an abstractmethod"


# ---------------------------------------------------------------------------
# 4.3  export_inventory is an abstract method
# ---------------------------------------------------------------------------


def test_export_inventory_is_abstract_method() -> None:
    """export_inventory is decorated with @abstractmethod."""
    method = IKeyInventoryExporter.export_inventory
    assert getattr(
        method, "__isabstractmethod__", False
    ), "export_inventory should be an abstractmethod"


# ---------------------------------------------------------------------------
# 4.4  Cannot instantiate IKeyInventoryExporter without implementations
# ---------------------------------------------------------------------------


def test_cannot_instantiate_abc_without_implementations() -> None:
    """Instantiating IKeyInventoryExporter directly raises TypeError."""
    with pytest.raises(TypeError, match="abstract method"):
        IKeyInventoryExporter()


# ---------------------------------------------------------------------------
# 4.5  export_snapshot signature: provider_name: str, db_manager, returns None
# ---------------------------------------------------------------------------


def test_export_snapshot_signature_accepts_provider_name_and_db_manager() -> None:
    """export_snapshot accepts provider_name: str and db_manager, returns None."""
    sig = inspect.signature(IKeyInventoryExporter.export_snapshot)
    params = sig.parameters

    # 'self' is always the first parameter; skip it.
    non_self_params = {name: p for name, p in params.items() if name != "self"}

    assert (
        "provider_name" in non_self_params
    ), "export_snapshot must have a 'provider_name' parameter"
    assert (
        non_self_params["provider_name"].annotation == "str"
    ), "export_snapshot's provider_name should be annotated as str"

    assert (
        "db_manager" in non_self_params
    ), "export_snapshot must have a 'db_manager' parameter"
    # With `from __future__ import annotations`, annotations are strings.
    assert "DatabaseManager" in str(
        non_self_params["db_manager"].annotation
    ), "export_snapshot's db_manager should be annotated as DatabaseManager"

    assert (
        sig.return_annotation is None or sig.return_annotation == "None"
    ), "export_snapshot should return None"


# ---------------------------------------------------------------------------
# 4.6  export_inventory signature: provider_name, db_manager, statuses: list[str], returns None
# ---------------------------------------------------------------------------


def test_export_inventory_signature_accepts_statuses() -> None:
    """export_inventory accepts provider_name: str, db_manager, statuses: list[str], returns None."""
    sig = inspect.signature(IKeyInventoryExporter.export_inventory)
    params = sig.parameters

    non_self_params = {name: p for name, p in params.items() if name != "self"}

    assert (
        "provider_name" in non_self_params
    ), "export_inventory must have a 'provider_name' parameter"
    assert (
        non_self_params["provider_name"].annotation == "str"
    ), "export_inventory's provider_name should be annotated as str"

    assert (
        "db_manager" in non_self_params
    ), "export_inventory must have a 'db_manager' parameter"
    assert "DatabaseManager" in str(
        non_self_params["db_manager"].annotation
    ), "export_inventory's db_manager should be annotated as DatabaseManager"

    assert (
        "statuses" in non_self_params
    ), "export_inventory must have a 'statuses' parameter"
    assert "list[str]" in str(
        non_self_params["statuses"].annotation
    ), "export_inventory's statuses should be annotated as list[str]"

    assert (
        sig.return_annotation is None or sig.return_annotation == "None"
    ), "export_inventory should return None"



