#!/usr/bin/env python3

"""Tests for DatabaseTableHealth frozen dataclass — field count, accessibility,
immutability, zero-ratio edge case, and None timestamp acceptance."""

import dataclasses
from datetime import datetime

import pytest

from src.core.models import DatabaseTableHealth

# ---------------------------------------------------------------------------
# N1: Creation — all 6 fields accessible and match
# ---------------------------------------------------------------------------


def test_database_table_health_creation_all_fields() -> None:
    """All 6 fields are accessible and match the values passed at creation."""
    vacuum_ts = datetime(2026, 4, 28, 10, 0, 0)
    analyze_ts = datetime(2026, 4, 29, 12, 30, 0)
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=10000,
        last_vacuum=vacuum_ts,
        last_analyze=analyze_ts,
        dead_tuple_ratio=0.05,
    )
    assert health.table_name == "public.api_keys"
    assert health.n_dead_tup == 500
    assert health.n_live_tup == 10000
    assert health.last_vacuum == vacuum_ts
    assert health.last_analyze == analyze_ts
    assert health.dead_tuple_ratio == 0.05


# ---------------------------------------------------------------------------
# N2: Frozen / immutability
# ---------------------------------------------------------------------------


def test_database_table_health_frozen_immutable() -> None:
    """Assigning to a field on a frozen dataclass raises FrozenInstanceError."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=10000,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.05,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        health.n_dead_tup = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# N3: Field count — exactly 6 fields
# ---------------------------------------------------------------------------


def test_database_table_health_field_count() -> None:
    """DatabaseTableHealth has exactly 6 dataclass fields."""
    fields = dataclasses.fields(DatabaseTableHealth)
    assert len(fields) == 6


# ---------------------------------------------------------------------------
# N4: Field names — expected set of 6 names
# ---------------------------------------------------------------------------


def test_database_table_health_field_names() -> None:
    """Field names match the expected set of 6."""
    fields = dataclasses.fields(DatabaseTableHealth)
    field_names = {f.name for f in fields}
    assert field_names == {
        "table_name",
        "n_dead_tup",
        "n_live_tup",
        "last_vacuum",
        "last_analyze",
        "dead_tuple_ratio",
    }


# ---------------------------------------------------------------------------
# N5: Zero live tuples — ratio is 0.0, no division error
# ---------------------------------------------------------------------------


def test_database_table_health_zero_live_tuples_ratio_is_zero() -> None:
    """When n_dead_tup=0 and n_live_tup=0, dead_tuple_ratio is 0.0 (no division error)."""
    health = DatabaseTableHealth(
        table_name="public.empty_table",
        n_dead_tup=0,
        n_live_tup=0,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.0,
    )
    assert health.dead_tuple_ratio == 0.0


# ---------------------------------------------------------------------------
# N6: None timestamps accepted
# ---------------------------------------------------------------------------


def test_database_table_health_none_timestamps() -> None:
    """last_vacuum=None and last_analyze=None are accepted without error."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=10000,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.05,
    )
    assert health.last_vacuum is None
    assert health.last_analyze is None
