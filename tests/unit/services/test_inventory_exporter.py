#!/usr/bin/env python3

"""
Unit tests for KeyInventoryExporter service (Group 5).

Tests the export_snapshot and export_inventory methods of KeyInventoryExporter,
verifying database queries, NDJSON file writing, and interface compliance.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.interfaces import IKeyInventoryExporter
from src.services.inventory_exporter import KeyInventoryExporter

# ── Helpers ──────────────────────────────────────────────────────────────────

PROVIDER_NAME = "gemini-pro-home"


def _make_snapshot_rows(
    n: int = 3,
    key_value_prefix: str = "sk-ant-api03-",
    status: str = "valid",
) -> list[dict[str, object]]:
    """Create mock DB rows for the snapshot query (includes status column)."""
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "key_id": i,
                "key_value": f"{key_value_prefix}{i:04d}-xxxx-yyyy-zzzz",
                "model_name": f"gemini-{i}-pro",
                "status": status,
                "next_check_time": datetime(2026, 4, 30, 14, i * 10, 0, tzinfo=UTC),
            }
        )
    return rows


def _make_inventory_rows(
    n: int = 2,
    key_value_prefix: str = "sk-ant-api03-",
) -> list[dict[str, object]]:
    """Create mock DB rows for the inventory query (no status column)."""
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "key_id": i,
                "key_value": f"{key_value_prefix}{i:04d}-xxxx-yyyy-zzzz",
                "model_name": f"gemini-{i}-pro",
                "next_check_time": datetime(2026, 4, 30, 14, i * 10, 0, tzinfo=UTC),
            }
        )
    return rows


def _make_mock_pool(rows: list[dict[str, object]]) -> MagicMock:
    """Build a mock asyncpg Pool whose acquire() yields a connection
    returning *rows* from fetch()."""
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False
    return mock_pool


def _make_mock_pool_multi_fetch(
    fetch_results: list[list[dict[str, object]]],
) -> MagicMock:
    """Build a mock pool where fetch() returns different results on each call
    (for export_inventory with multiple statuses)."""
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(side_effect=fetch_results)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False
    return mock_pool


# ── Tests ────────────────────────────────────────────────────────────────────


class TestKeyInventoryExporter:
    """Unit tests for KeyInventoryExporter (Group 5)."""

    # ── 5.9: Interface compliance ──────────────────────────────────────────

    def test_key_inventory_exporter_implements_interface(self) -> None:
        """KeyInventoryExporter inherits IKeyInventoryExporter."""
        assert issubclass(KeyInventoryExporter, IKeyInventoryExporter)

    # ── 5.1: export_snapshot queries DB and writes NDJSON ──────────────────

    @pytest.mark.asyncio
    async def test_export_snapshot_queries_all_keys_and_writes_ndjson(self) -> None:
        """export_snapshot queries DB and writes all_keys.ndjson."""
        exporter = KeyInventoryExporter()
        rows = _make_snapshot_rows(3, status="valid")
        mock_pool = _make_mock_pool(rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_snapshot(PROVIDER_NAME, AsyncMock())

        # Verify the SQL query was executed via conn.fetch
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        sql = call_args[0][0]
        assert "SELECT" in sql
        assert "api_keys" in sql
        assert "key_model_status" in sql
        assert "providers" in sql
        assert call_args[0][1] == PROVIDER_NAME

        # Verify write_atomic_ndjson was called with the correct path
        mock_write.assert_called_once()
        assert mock_write.call_args[0][0] == f"data/{PROVIDER_NAME}/all_keys.ndjson"

    # ── 5.2: NDJSON contains required fields ──────────────────────────────

    @pytest.mark.asyncio
    async def test_export_snapshot_ndjson_contains_required_fields(self) -> None:
        """Each NDJSON record has key_id, key_prefix, model_name, status, next_check_time."""
        exporter = KeyInventoryExporter()
        rows = _make_snapshot_rows(2, status="valid")
        mock_pool = _make_mock_pool(rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_snapshot(PROVIDER_NAME, AsyncMock())

        records = mock_write.call_args[0][1]
        required_fields = {
            "key_id",
            "key_prefix",
            "model_name",
            "status",
            "next_check_time",
        }
        for record in records:
            assert required_fields.issubset(
                record.keys()
            ), f"Missing fields: {required_fields - record.keys()}"

    # ── 5.3: key_prefix is first 10 chars ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_export_snapshot_key_prefix_is_first_10_chars(self) -> None:
        """key_prefix == key_value[:10] for each record."""
        exporter = KeyInventoryExporter()
        rows = _make_snapshot_rows(3, key_value_prefix="sk-ant-api0")
        mock_pool = _make_mock_pool(rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_snapshot(PROVIDER_NAME, AsyncMock())

        records = mock_write.call_args[0][1]
        for record in records:
            original_row = next(r for r in rows if r["key_id"] == record["key_id"])
            expected_prefix: str = original_row["key_value"][:10]
            assert (
                record["key_prefix"] == expected_prefix
            ), f"Expected key_prefix '{expected_prefix}', got '{record['key_prefix']}'"

    # ── 5.4: export_inventory creates status subdirectories ───────────────

    @pytest.mark.asyncio
    async def test_export_inventory_creates_status_subdirectories(self) -> None:
        """export_inventory with multiple statuses creates subdirectories for each."""
        exporter = KeyInventoryExporter()

        valid_rows = _make_inventory_rows(2)
        no_quota_rows = _make_inventory_rows(1)

        mock_pool = _make_mock_pool_multi_fetch([valid_rows, no_quota_rows])
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_inventory(
                PROVIDER_NAME, AsyncMock(), ["valid", "no_quota"]
            )

        assert mock_write.call_count == 2
        paths = [call[0][0] for call in mock_write.call_args_list]
        assert f"data/{PROVIDER_NAME}/valid/keys.ndjson" in paths
        assert f"data/{PROVIDER_NAME}/no_quota/keys.ndjson" in paths

    # ── 5.5: export_inventory filters by status ───────────────────────────

    @pytest.mark.asyncio
    async def test_export_inventory_filters_by_status(self) -> None:
        """valid/keys.ndjson only contains entries with status 'valid'."""
        exporter = KeyInventoryExporter()

        valid_rows = _make_inventory_rows(3)
        mock_pool = _make_mock_pool(valid_rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_inventory(PROVIDER_NAME, AsyncMock(), ["valid"])

        records = mock_write.call_args[0][1]
        for record in records:
            assert record["status"] == "valid"

    # ── 5.6: empty status list is a noop ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_export_inventory_empty_status_list_noop(self) -> None:
        """Empty statuses list — no files created, no errors raised."""
        exporter = KeyInventoryExporter()
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=MagicMock()),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_inventory(PROVIDER_NAME, AsyncMock(), [])

        mock_write.assert_not_called()

    # ── 5.7: single status creates one subdirectory ────────────────────────

    @pytest.mark.asyncio
    async def test_export_inventory_single_status(self) -> None:
        """Single status creates exactly one subdirectory."""
        exporter = KeyInventoryExporter()

        rate_limited_rows = _make_inventory_rows(2)
        mock_pool = _make_mock_pool(rate_limited_rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_inventory(
                PROVIDER_NAME, AsyncMock(), ["rate_limited"]
            )

        mock_write.assert_called_once()
        assert (
            mock_write.call_args[0][0]
            == f"data/{PROVIDER_NAME}/rate_limited/keys.ndjson"
        )

    # ── 5.8: empty DB result creates empty NDJSON ─────────────────────────

    @pytest.mark.asyncio
    async def test_export_snapshot_empty_result_creates_empty_file(self) -> None:
        """Empty DB result creates an empty NDJSON file (empty records list)."""
        exporter = KeyInventoryExporter()

        mock_pool = _make_mock_pool([])
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_snapshot(PROVIDER_NAME, AsyncMock())

        mock_write.assert_called_once()
        assert mock_write.call_args[0][0] == f"data/{PROVIDER_NAME}/all_keys.ndjson"
        assert mock_write.call_args[0][1] == []

    # ── 5.10: export_snapshot uses write_atomic_ndjson ─────────────────────

    @pytest.mark.asyncio
    async def test_export_snapshot_uses_write_atomic_ndjson(self) -> None:
        """Verifies write_atomic_ndjson is called with correct path and records."""
        exporter = KeyInventoryExporter()
        rows = _make_snapshot_rows(2, status="valid")
        mock_pool = _make_mock_pool(rows)
        mock_write = MagicMock()

        with (
            patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
            patch("src.services.inventory_exporter.write_atomic_ndjson", mock_write),
        ):
            await exporter.export_snapshot(PROVIDER_NAME, AsyncMock())

        mock_write.assert_called_once()
        call_args = mock_write.call_args[0]
        # Verify path
        assert call_args[0] == f"data/{PROVIDER_NAME}/all_keys.ndjson"
        # Verify records is a list of dicts with correct length
        assert isinstance(call_args[1], list)
        assert len(call_args[1]) == 2
        for record in call_args[1]:
            assert isinstance(record, dict)
