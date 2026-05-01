#!/usr/bin/env python3

"""Tests for IKeyPurger ABC — Group 1: Core interface contract.

Verifies that IKeyPurger is a proper ABC with two abstract methods,
cannot be instantiated without implementations, and has correct
signatures.
"""

import inspect
from abc import ABC

import pytest

from src.core.interfaces import IKeyPurger

# ---------------------------------------------------------------------------
# N7: IKeyPurger inherits ABC
# ---------------------------------------------------------------------------


def test_ikey_purger_is_abc() -> None:
    """IKeyPurger is a subclass of ABC."""
    assert issubclass(IKeyPurger, ABC), "IKeyPurger should inherit from ABC"


# ---------------------------------------------------------------------------
# N8: Cannot instantiate IKeyPurger without implementations
# ---------------------------------------------------------------------------


def test_ikey_purger_cannot_instantiate() -> None:
    """Instantiating IKeyPurger directly raises TypeError with 'abstract method'."""
    with pytest.raises(TypeError, match="abstract method"):
        IKeyPurger()


# ---------------------------------------------------------------------------
# N9: purge_provider is an abstract method
# ---------------------------------------------------------------------------


def test_purge_provider_is_abstract_method() -> None:
    """purge_provider is decorated with @abstractmethod."""
    method = IKeyPurger.purge_provider
    assert getattr(
        method, "__isabstractmethod__", False
    ), "purge_provider should be an abstractmethod"


# ---------------------------------------------------------------------------
# N10: purge_stopped_keys is an abstract method
# ---------------------------------------------------------------------------


def test_purge_stopped_keys_is_abstract_method() -> None:
    """purge_stopped_keys is decorated with @abstractmethod."""
    method = IKeyPurger.purge_stopped_keys
    assert getattr(
        method, "__isabstractmethod__", False
    ), "purge_stopped_keys should be an abstractmethod"


# ---------------------------------------------------------------------------
# N11: purge_provider signature
# ---------------------------------------------------------------------------


def test_purge_provider_signature() -> None:
    """purge_provider(self, provider_id: int, db_manager: DatabaseManager) -> int."""
    sig = inspect.signature(IKeyPurger.purge_provider)
    params = sig.parameters

    non_self_params = {name: p for name, p in params.items() if name != "self"}

    assert (
        len(non_self_params) == 2
    ), f"purge_provider should have 2 parameters beyond self, got {len(non_self_params)}"

    assert "provider_id" in non_self_params, "purge_provider must have 'provider_id'"
    assert (
        non_self_params["provider_id"].annotation == "int"
    ), "purge_provider's provider_id should be annotated as int"

    assert "db_manager" in non_self_params, "purge_provider must have 'db_manager'"
    assert "DatabaseManager" in str(
        non_self_params["db_manager"].annotation
    ), "purge_provider's db_manager should be annotated as DatabaseManager"

    assert sig.return_annotation == "int", "purge_provider should return int"


# ---------------------------------------------------------------------------
# N12: purge_stopped_keys signature
# ---------------------------------------------------------------------------


def test_purge_stopped_keys_signature() -> None:
    """purge_stopped_keys(self, provider_name: str, provider_id: int,
    cutoff: datetime, db_manager: DatabaseManager) -> int."""
    sig = inspect.signature(IKeyPurger.purge_stopped_keys)
    params = sig.parameters

    non_self_params = {name: p for name, p in params.items() if name != "self"}

    assert (
        len(non_self_params) == 4
    ), f"purge_stopped_keys should have 4 parameters beyond self, got {len(non_self_params)}"

    assert (
        "provider_name" in non_self_params
    ), "purge_stopped_keys must have 'provider_name'"
    assert (
        non_self_params["provider_name"].annotation == "str"
    ), "purge_stopped_keys's provider_name should be annotated as str"

    assert (
        "provider_id" in non_self_params
    ), "purge_stopped_keys must have 'provider_id'"
    assert (
        non_self_params["provider_id"].annotation == "int"
    ), "purge_stopped_keys's provider_id should be annotated as int"

    assert "cutoff" in non_self_params, "purge_stopped_keys must have 'cutoff'"
    assert "datetime" in str(
        non_self_params["cutoff"].annotation
    ), "purge_stopped_keys's cutoff should be annotated as datetime"

    assert "db_manager" in non_self_params, "purge_stopped_keys must have 'db_manager'"
    assert "DatabaseManager" in str(
        non_self_params["db_manager"].annotation
    ), "purge_stopped_keys's db_manager should be annotated as DatabaseManager"

    assert sig.return_annotation == "int", "purge_stopped_keys should return int"
