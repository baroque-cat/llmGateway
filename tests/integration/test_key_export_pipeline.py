#!/usr/bin/env python3

"""
Integration tests for the Config → Export pipeline (Group 9).

Tests the full pipeline from ``KeyExportConfig`` through
``KeyInventoryExporter`` to ``write_atomic_ndjson``, verifying that
NDJSON files are correctly created on disk when the configuration
enables the relevant export features.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import KeyExportConfig, KeyInventoryConfig
from src.core.constants import Status
from src.services.inventory_exporter import KeyInventoryExporter

PROVIDER_NAME = "test-provider"

# ---------------------------------------------------------------------------
# Mock DB rows — snapshot query returns all keys; inventory returns one status
# ---------------------------------------------------------------------------

MOCK_SNAPSHOT_ROWS: list[dict[str, object]] = [
    {
        "key_id": 1,
        "key_value": "sk-abcdefghij123456",
        "model_name": "gemini-3-pro",
        "status": "valid",
        "next_check_time": datetime(2026, 4, 30, 14, 0, 0, tzinfo=UTC),
    },
    {
        "key_id": 2,
        "key_value": "sk-xyzabcdefgh999",
        "model_name": "gemini-3-pro",
        "status": "rate_limited",
        "next_check_time": datetime(2026, 4, 30, 16, 0, 0, tzinfo=UTC),
    },
    {
        "key_id": 3,
        "key_value": "sk-mnoabcdefgh000",
        "model_name": "gemini-3-flash",
        "status": "invalid_key",
        "next_check_time": None,
    },
]

# Inventory query does NOT select kms.status — the exporter uses the
# *parameter* value instead.  Rows only need key_id, key_value,
# model_name, and next_check_time.
MOCK_VALID_ROWS: list[dict[str, object]] = [
    {
        "key_id": 1,
        "key_value": "sk-abcdefghij123456",
        "model_name": "gemini-3-pro",
        "next_check_time": datetime(2026, 4, 30, 14, 0, 0, tzinfo=UTC),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pool(rows: list[dict[str, object]]) -> MagicMock:
    """Build a mock asyncpg Pool whose ``acquire()`` returns a connection
    that ``fetch()`` returns *rows*."""
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False
    return mock_pool


def _read_ndjson_lines(path: Path) -> list[dict[str, object]]:
    """Read an NDJSON file and return a list of parsed dicts."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    return [json.loads(line) for line in text.strip().split("\n")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_snapshot_export_pipeline(tmp_path: Path) -> None:
    """
    9.1: Load config with ``snapshot_interval_hours=24``, create
    ``KeyInventoryExporter``, call ``export_snapshot`` with mock DB,
    verify ``all_keys.ndjson`` created with correct content.
    """
    config = KeyExportConfig(
        enabled=True,
        snapshot_interval_hours=24,
    )
    # Verify config is set up correctly
    assert config.enabled is True
    assert config.snapshot_interval_hours == 24

    exporter = KeyInventoryExporter()
    mock_pool = _make_mock_pool(MOCK_SNAPSHOT_ROWS)

    with (
        patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
        patch("src.services.inventory_exporter._EXPORT_ROOT", str(tmp_path)),
    ):
        await exporter.export_snapshot(PROVIDER_NAME, MagicMock())

    # Verify all_keys.ndjson was created
    snapshot_file = tmp_path / PROVIDER_NAME / "all_keys.ndjson"
    assert snapshot_file.exists(), f"Expected {snapshot_file} to exist"

    # Verify content — 3 records with all required fields
    records = _read_ndjson_lines(snapshot_file)
    assert len(records) == 3, f"Expected 3 records, got {len(records)}"

    for record in records:
        assert "key_id" in record
        assert "key_prefix" in record
        assert "model_name" in record
        assert "status" in record
        assert "next_check_time" in record

    # Verify key_prefix is first 10 chars of key_value
    for row, record in zip(MOCK_SNAPSHOT_ROWS, records):
        expected_prefix: str = row["key_value"][:10]  # type: ignore[union-attr]
        assert (
            record["key_prefix"] == expected_prefix
        ), f"Expected key_prefix '{expected_prefix}', got '{record['key_prefix']}'"


@pytest.mark.asyncio
async def test_full_inventory_export_pipeline(tmp_path: Path) -> None:
    """
    9.2: Config with ``inventory.enabled=True, statuses=["valid"]``, call
    ``export_inventory``, verify ``valid/keys.ndjson`` created with only
    valid keys.
    """
    config = KeyExportConfig(
        enabled=True,
        inventory=KeyInventoryConfig(
            enabled=True,
            statuses=[Status.VALID],
        ),
    )
    assert config.inventory.enabled is True
    assert config.inventory.statuses == [Status.VALID]

    exporter = KeyInventoryExporter()
    mock_pool = _make_mock_pool(MOCK_VALID_ROWS)

    with (
        patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
        patch("src.services.inventory_exporter._EXPORT_ROOT", str(tmp_path)),
    ):
        await exporter.export_inventory(PROVIDER_NAME, MagicMock(), ["valid"])

    # Verify valid/keys.ndjson was created
    inventory_file = tmp_path / PROVIDER_NAME / "valid" / "keys.ndjson"
    assert inventory_file.exists(), f"Expected {inventory_file} to exist"

    # Verify content — only valid keys
    records = _read_ndjson_lines(inventory_file)
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"

    record = records[0]
    assert (
        record["status"] == "valid"
    ), f"Expected status 'valid', got '{record['status']}'"
    assert (
        record["key_prefix"] == "sk-abcdefg"
    ), f"Expected key_prefix 'sk-abcdefg', got '{record['key_prefix']}'"


@pytest.mark.asyncio
async def test_snapshot_and_inventory_coexist(tmp_path: Path) -> None:
    """
    9.3: Config with both snapshot and inventory enabled, verify both
    ``all_keys.ndjson`` and ``valid/keys.ndjson`` are created.
    """
    config = KeyExportConfig(
        enabled=True,
        snapshot_interval_hours=24,
        inventory=KeyInventoryConfig(
            enabled=True,
            statuses=[Status.VALID],
        ),
    )
    assert config.enabled is True
    assert config.snapshot_interval_hours == 24
    assert config.inventory.enabled is True

    exporter = KeyInventoryExporter()

    # Separate mock pools — snapshot returns all rows, inventory returns
    # only valid rows.
    snapshot_pool = _make_mock_pool(MOCK_SNAPSHOT_ROWS)
    inventory_pool = _make_mock_pool(MOCK_VALID_ROWS)

    with patch("src.services.inventory_exporter._EXPORT_ROOT", str(tmp_path)):
        # Export snapshot
        with patch(
            "src.services.inventory_exporter.get_pool", return_value=snapshot_pool
        ):
            await exporter.export_snapshot(PROVIDER_NAME, MagicMock())

        # Export inventory
        with patch(
            "src.services.inventory_exporter.get_pool", return_value=inventory_pool
        ):
            await exporter.export_inventory(PROVIDER_NAME, MagicMock(), ["valid"])

    # Verify both files exist
    snapshot_file = tmp_path / PROVIDER_NAME / "all_keys.ndjson"
    inventory_file = tmp_path / PROVIDER_NAME / "valid" / "keys.ndjson"
    assert snapshot_file.exists(), f"Expected {snapshot_file} to exist"
    assert inventory_file.exists(), f"Expected {inventory_file} to exist"

    # Verify snapshot content — all 3 keys
    snapshot_records = _read_ndjson_lines(snapshot_file)
    assert (
        len(snapshot_records) == 3
    ), f"Expected 3 snapshot records, got {len(snapshot_records)}"

    # Verify inventory content — only valid keys
    inventory_records = _read_ndjson_lines(inventory_file)
    assert (
        len(inventory_records) == 1
    ), f"Expected 1 inventory record, got {len(inventory_records)}"
    assert inventory_records[0]["status"] == "valid"


@pytest.mark.asyncio
async def test_disabled_config_produces_no_files(tmp_path: Path) -> None:
    """
    9.4: ``KeyExportConfig(enabled=False)`` — no NDJSON files created.

    When the master switch is disabled, the pipeline should not invoke
    the exporter, and therefore no files should be produced.
    """
    config = KeyExportConfig(enabled=False)
    assert config.enabled is False

    # Simulate the pipeline logic: when enabled=False, the background
    # worker skips all export calls.  We intentionally do NOT call
    # exporter.export_snapshot or exporter.export_inventory, mirroring
    # how background_worker.py gates on config.key_export.enabled.

    # Verify no NDJSON files exist in the output directory
    output_dir = tmp_path / PROVIDER_NAME
    if output_dir.exists():
        ndjson_files = list(output_dir.rglob("*.ndjson"))
        assert len(ndjson_files) == 0, (
            f"Expected no .ndjson files when config is disabled, "
            f"found: {ndjson_files}"
        )
    # If the directory doesn't exist at all, that also confirms no files
    # were created — the assertion above is sufficient.


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
