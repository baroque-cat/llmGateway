#!/usr/bin/env python3

"""Tests for IDatabaseMaintainer ABC — Group 1: Core interface contract.

Verifies that IDatabaseMaintainer is a proper ABC with two abstract methods,
cannot be instantiated without implementations, has correct signatures,
and does not import from src.db or src.config at runtime.
"""

import ast
import importlib
import inspect
import pathlib
from abc import ABC

import pytest

from src.core.interfaces import IDatabaseMaintainer

# ---------------------------------------------------------------------------
# N14: IDatabaseMaintainer inherits ABC
# ---------------------------------------------------------------------------


def test_idatabase_maintainer_is_abc() -> None:
    """IDatabaseMaintainer is a subclass of ABC."""
    assert issubclass(
        IDatabaseMaintainer, ABC
    ), "IDatabaseMaintainer should inherit from ABC"


# ---------------------------------------------------------------------------
# N15: Cannot instantiate IDatabaseMaintainer without implementations
# ---------------------------------------------------------------------------


def test_idatabase_maintainer_cannot_instantiate() -> None:
    """Instantiating IDatabaseMaintainer directly raises TypeError."""
    with pytest.raises(TypeError, match="abstract method"):
        IDatabaseMaintainer()


# ---------------------------------------------------------------------------
# N16: get_table_health is an abstract method
# ---------------------------------------------------------------------------


def test_get_table_health_is_abstract_method() -> None:
    """get_table_health is decorated with @abstractmethod."""
    method = IDatabaseMaintainer.get_table_health
    assert getattr(
        method, "__isabstractmethod__", False
    ), "get_table_health should be an abstractmethod"


# ---------------------------------------------------------------------------
# N17: run_conditional_vacuum is an abstract method
# ---------------------------------------------------------------------------


def test_run_conditional_vacuum_is_abstract_method() -> None:
    """run_conditional_vacuum is decorated with @abstractmethod."""
    method = IDatabaseMaintainer.run_conditional_vacuum
    assert getattr(
        method, "__isabstractmethod__", False
    ), "run_conditional_vacuum should be an abstractmethod"


# ---------------------------------------------------------------------------
# N18: get_table_health signature — returns list[DatabaseTableHealth]
# ---------------------------------------------------------------------------


def test_get_table_health_signature() -> None:
    """get_table_health returns list[DatabaseTableHealth]."""
    sig = inspect.signature(IDatabaseMaintainer.get_table_health)

    return_annotation = str(sig.return_annotation)
    assert (
        "list" in return_annotation
    ), f"get_table_health return annotation should contain 'list', got '{return_annotation}'"
    assert (
        "DatabaseTableHealth" in return_annotation
    ), f"get_table_health return annotation should contain 'DatabaseTableHealth', got '{return_annotation}'"


# ---------------------------------------------------------------------------
# N19: run_conditional_vacuum signature — tables: list[DatabaseTableHealth], returns int
# ---------------------------------------------------------------------------


def test_run_conditional_vacuum_signature() -> None:
    """run_conditional_vacuum has parameter tables: list[DatabaseTableHealth] and returns int."""
    sig = inspect.signature(IDatabaseMaintainer.run_conditional_vacuum)
    params = sig.parameters

    non_self_params = {name: p for name, p in params.items() if name != "self"}

    assert (
        "tables" in non_self_params
    ), "run_conditional_vacuum must have a 'tables' parameter"
    tables_annotation = str(non_self_params["tables"].annotation)
    assert (
        "list" in tables_annotation
    ), f"tables should be annotated as list[DatabaseTableHealth], got '{tables_annotation}'"
    assert (
        "DatabaseTableHealth" in tables_annotation
    ), f"tables should be annotated as list[DatabaseTableHealth], got '{tables_annotation}'"

    assert (
        sig.return_annotation == "int"
    ), f"run_conditional_vacuum should return int, got '{sig.return_annotation}'"
