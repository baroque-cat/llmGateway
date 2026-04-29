#!/usr/bin/env python3

"""Tests for KeyExportSnapshot frozen dataclass — field count, accessibility,
immutability, and dict conversion."""

import dataclasses

import pytest

from src.core.models import KeyExportSnapshot

# ---------------------------------------------------------------------------
# 3.1: Creation — all 5 fields accessible and match
# ---------------------------------------------------------------------------


def test_key_export_snapshot_creation_all_fields() -> None:
    """All 5 fields are accessible and match the values passed at creation."""
    snapshot = KeyExportSnapshot(
        key_id=1,
        key_prefix="sk-abc12345",
        model_name="gemini-3-pro",
        status="valid",
        next_check_time="2026-04-30T14:00:00Z",
    )
    assert snapshot.key_id == 1
    assert snapshot.key_prefix == "sk-abc12345"
    assert snapshot.model_name == "gemini-3-pro"
    assert snapshot.status == "valid"
    assert snapshot.next_check_time == "2026-04-30T14:00:00Z"


# ---------------------------------------------------------------------------
# 3.2: Frozen / immutability
# ---------------------------------------------------------------------------


def test_key_export_snapshot_frozen_immutable() -> None:
    """Assigning to a field on a frozen dataclass raises FrozenInstanceError."""
    snapshot = KeyExportSnapshot(
        key_id=1,
        key_prefix="sk-abc12345",
        model_name="gemini-3-pro",
        status="valid",
        next_check_time="2026-04-30T14:00:00Z",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.key_id = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3.3: Field count — exactly 5 fields
# ---------------------------------------------------------------------------


def test_key_export_snapshot_field_count() -> None:
    """KeyExportSnapshot has exactly 5 dataclass fields."""
    fields = dataclasses.fields(KeyExportSnapshot)
    assert len(fields) == 5
    field_names = {f.name for f in fields}
    assert field_names == {
        "key_id",
        "key_prefix",
        "model_name",
        "status",
        "next_check_time",
    }


# ---------------------------------------------------------------------------
# 3.4: to_dict conversion — dataclasses.asdict produces dict with 5 keys
# ---------------------------------------------------------------------------


def test_key_export_snapshot_to_dict_conversion() -> None:
    """dataclasses.asdict(snapshot) produces a dict with 5 keys matching values."""
    snapshot = KeyExportSnapshot(
        key_id=1,
        key_prefix="sk-abc12345",
        model_name="gemini-3-pro",
        status="valid",
        next_check_time="2026-04-30T14:00:00Z",
    )
    result = dataclasses.asdict(snapshot)
    assert isinstance(result, dict)
    assert len(result) == 5
    assert result == {
        "key_id": 1,
        "key_prefix": "sk-abc12345",
        "model_name": "gemini-3-pro",
        "status": "valid",
        "next_check_time": "2026-04-30T14:00:00Z",
    }
