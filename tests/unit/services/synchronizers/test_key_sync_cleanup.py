#!/usr/bin/env python3

"""
Unit tests for raw file cleanup in KeySyncer and read_keys_from_directory file_map.

Group 6: Services — Raw file cleanup / KeySyncer + read_keys_from_directory

Tests:
 1. read_keys_from_directory returns file_map with mtime
 2. file_map mtime matches actual os.stat().st_mtime
 3. empty dir returns (set(), {})
 4. nonexistent dir returns (set(), {})
 5. cleanup removes unchanged file after sync (rename to .trash/ then unlink)
 6. cleanup keeps modified file (mtime changed, warning logged)
 7. cleanup skips already-deleted file gracefully (debug log)
 8. cleanup gated by clean_raw_after_sync=True
 9. cleanup gated by clean_raw_after_sync=False
10. cleanup rename-to-trash then unlink order verified
11. cleanup trash path format: {timestamp}_{uuid8}_{basename}
12. cleanup only on successful sync (exception → files NOT deleted)
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.accessor import ConfigAccessor
from src.core.interfaces import ProviderKeyState
from src.db.database import DatabaseManager
from src.services.synchronizers.key_sync import KeySyncer, read_keys_from_directory

# ---------------------------------------------------------------------------
# Tests 1–4: read_keys_from_directory file_map behaviour
# ---------------------------------------------------------------------------


def test_read_keys_from_directory_returns_file_map_with_mtime(tmp_path):
    """Returns (keys, file_map) with dict[str, float] mapping absolute paths to mtime."""
    d = tmp_path / "keys"
    d.mkdir()
    (d / "keys.txt").write_text("sk-test-key", encoding="utf-8")

    keys, file_map = read_keys_from_directory(str(d))

    assert isinstance(file_map, dict)
    assert len(file_map) == 1
    filepath = os.path.join(str(d), "keys.txt")
    assert filepath in file_map
    assert isinstance(file_map[filepath], float)


def test_read_keys_from_directory_file_map_mtime_matches_actual(tmp_path):
    """mtime in file_map matches os.stat().st_mtime for the file."""
    d = tmp_path / "keys"
    d.mkdir()
    (d / "keys.txt").write_text("sk-test-key", encoding="utf-8")

    keys, file_map = read_keys_from_directory(str(d))

    filepath = os.path.join(str(d), "keys.txt")
    actual_mtime = os.stat(filepath).st_mtime
    assert file_map[filepath] == actual_mtime


def test_read_keys_from_directory_empty_dir_returns_empty_map(tmp_path):
    """Empty directory returns (set(), {})."""
    d = tmp_path / "empty_keys"
    d.mkdir()

    keys, file_map = read_keys_from_directory(str(d))

    assert keys == set()
    assert file_map == {}


def test_read_keys_from_directory_nonexistent_dir_returns_empty_map():
    """Nonexistent directory returns (set(), {})."""
    keys, file_map = read_keys_from_directory(
        "/nonexistent/path/that/does/not/exist12345"
    )

    assert keys == set()
    assert file_map == {}


# ---------------------------------------------------------------------------
# Helper: build a KeySyncer with mocked accessor / db_manager
# ---------------------------------------------------------------------------


def _make_syncer(
    clean_raw_after_sync: bool = True,
) -> tuple[KeySyncer, MagicMock, MagicMock]:
    """Create a KeySyncer with mocked dependencies.

    Returns (syncer, mock_accessor, mock_db_manager).
    The accessor.get_provider() return value has
    key_export.clean_raw_after_sync set to the given flag.
    """
    mock_accessor = MagicMock(spec=ConfigAccessor)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.keys = MagicMock()
    mock_db_manager.keys.sync = AsyncMock()

    mock_provider_config = MagicMock()
    mock_provider_config.key_export = MagicMock()
    mock_provider_config.key_export.clean_raw_after_sync = clean_raw_after_sync
    mock_accessor.get_provider.return_value = mock_provider_config

    syncer = KeySyncer(mock_accessor, mock_db_manager)
    return syncer, mock_accessor, mock_db_manager


# ---------------------------------------------------------------------------
# Tests 5–12: KeySyncer cleanup logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_unchanged_file_after_sync(tmp_path):
    """mtime matches → file renamed to .trash/ then unlinked."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with (
        patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
        patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
        patch("src.services.synchronizers.key_sync.os.makedirs"),
    ):
        await syncer.apply_state(provider_id_map, desired_state)

        assert mock_rename.called
        assert mock_unlink.called


@pytest.mark.asyncio
async def test_cleanup_keeps_modified_file(tmp_path, caplog):
    """mtime changed → file NOT deleted, warning logged."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    # Use a deliberately wrong mtime to simulate file modification
    recorded_mtime = os.stat(filepath).st_mtime - 100.0

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with caplog.at_level(logging.WARNING, logger="src.services.synchronizers.key_sync"):
        with (
            patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
            patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
        ):
            await syncer.apply_state(provider_id_map, desired_state)

            # File should NOT be renamed/unlinked
            mock_rename.assert_not_called()
            mock_unlink.assert_not_called()
            # Warning should be logged about modified file
            assert "modified since read" in caplog.text


@pytest.mark.asyncio
async def test_cleanup_skips_already_deleted_file_gracefully(caplog):
    """File gone between read and cleanup → skip with debug log."""
    nonexistent_path = "/tmp/definitely_not_here_keys_cleanup_test.txt"

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {nonexistent_path: 12345.0},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with caplog.at_level(logging.DEBUG, logger="src.services.synchronizers.key_sync"):
        with (
            patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
            patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
        ):
            await syncer.apply_state(provider_id_map, desired_state)

            mock_rename.assert_not_called()
            mock_unlink.assert_not_called()
            assert "already gone" in caplog.text.lower()


@pytest.mark.asyncio
async def test_cleanup_gated_by_clean_raw_after_sync_true(tmp_path):
    """Cleanup runs when clean_raw_after_sync=True."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with (
        patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
        patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
        patch("src.services.synchronizers.key_sync.os.makedirs"),
    ):
        await syncer.apply_state(provider_id_map, desired_state)

        assert mock_rename.called
        assert mock_unlink.called


@pytest.mark.asyncio
async def test_cleanup_gated_by_clean_raw_after_sync_false(tmp_path):
    """Cleanup does NOT run when clean_raw_after_sync=False."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, _ = _make_syncer(clean_raw_after_sync=False)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with (
        patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
        patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
    ):
        await syncer.apply_state(provider_id_map, desired_state)

        mock_rename.assert_not_called()
        mock_unlink.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_rename_to_trash_then_unlink(tmp_path):
    """Rename then unlink order verified."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    call_order: list[str] = []

    with (
        patch(
            "src.services.synchronizers.key_sync.os.rename",
            side_effect=lambda *a, **kw: call_order.append("rename"),
        ),
        patch(
            "src.services.synchronizers.key_sync.os.unlink",
            side_effect=lambda *a, **kw: call_order.append("unlink"),
        ),
        patch("src.services.synchronizers.key_sync.os.makedirs"),
    ):
        await syncer.apply_state(provider_id_map, desired_state)

        assert call_order == ["rename", "unlink"]


@pytest.mark.asyncio
async def test_cleanup_trash_path_format(tmp_path):
    """Trash name format: {timestamp}_{uuid8}_{basename}."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, _ = _make_syncer(clean_raw_after_sync=True)

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    fake_timestamp = 1700000000
    fake_uuid_hex = "a1b2c3d4e5f6a7b8"

    with (
        patch(
            "src.services.synchronizers.key_sync._time.time",
            return_value=float(fake_timestamp),
        ) as mock_time,
        patch("src.services.synchronizers.key_sync.uuid4") as mock_uuid,
        patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
        patch("src.services.synchronizers.key_sync.os.unlink"),
        patch("src.services.synchronizers.key_sync.os.makedirs"),
    ):
        mock_uuid.return_value.hex = fake_uuid_hex

        await syncer.apply_state(provider_id_map, desired_state)

        # Verify rename was called; second positional arg is the trash_path
        rename_call = mock_rename.call_args
        trash_path = rename_call[0][1]

        # Expected trash name: 1700000000_a1b2c3d4_keys.txt
        expected_trash_name = f"{fake_timestamp}_{fake_uuid_hex[:8]}_keys.txt"
        assert os.path.basename(trash_path) == expected_trash_name


@pytest.mark.asyncio
async def test_cleanup_after_sync_only_on_successful_sync(tmp_path):
    """sync raises exception → raw files NOT deleted."""
    d = tmp_path / "raw"
    d.mkdir()
    key_file = d / "keys.txt"
    key_file.write_text("sk-test", encoding="utf-8")

    filepath = str(key_file)
    recorded_mtime = os.stat(filepath).st_mtime

    syncer, _, mock_db_manager = _make_syncer(clean_raw_after_sync=True)
    # Make sync raise an exception
    mock_db_manager.keys.sync = AsyncMock(side_effect=RuntimeError("DB sync failed"))

    provider_state: ProviderKeyState = {
        "keys_from_files": {"sk-test"},
        "models_from_config": ["model1"],
        "file_map": {filepath: recorded_mtime},
    }
    desired_state = {"provider_a": provider_state}
    provider_id_map = {"provider_a": 1}

    with (
        patch("src.services.synchronizers.key_sync.os.rename") as mock_rename,
        patch("src.services.synchronizers.key_sync.os.unlink") as mock_unlink,
    ):
        await syncer.apply_state(provider_id_map, desired_state)

        # Cleanup should NOT have been attempted
        mock_rename.assert_not_called()
        mock_unlink.assert_not_called()
        # File should still exist on disk
        assert os.path.exists(filepath)
