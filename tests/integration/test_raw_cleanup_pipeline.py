#!/usr/bin/env python3

"""
Integration tests for the raw key file cleanup pipeline.

Group 10: Integration — Raw cleanup pipeline

Tests the full cycle: read_keys_from_directory → KeySyncer.apply_state → cleanup,
including startup .trash/ cleanup via _setup_directories.
"""

import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.accessor import ConfigAccessor
from src.core.interfaces import ProviderKeyState
from src.db.database import DatabaseManager
from src.services.keeper import _setup_directories
from src.services.synchronizers.key_sync import KeySyncer, read_keys_from_directory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw_dir(tmp_path: Path, provider_name: str) -> Path:
    """Create the data/<provider>/raw directory tree under tmp_path."""
    raw_dir = tmp_path / "data" / provider_name / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def _patched_os_path_join(data_root: str):
    """Return a replacement for os.path.join that redirects the literal
    ``"data"`` prefix to *data_root* so that cleanup paths stay on the same
    filesystem as the test key files inside tmp_path."""
    real_join = os.path.join

    def _join(*args: str) -> str:
        if args and args[0] == "data":
            return real_join(data_root, *args[1:])
        return real_join(*args)

    return _join


def _mock_accessor(
    provider_name: str, *, clean_raw_after_sync: bool = True
) -> MagicMock:
    """Build a mock ConfigAccessor for a single enabled provider."""
    accessor = MagicMock(spec=ConfigAccessor)
    provider = MagicMock()
    provider.enabled = True
    provider.key_export.clean_raw_after_sync = clean_raw_after_sync
    accessor.get_provider.return_value = provider
    accessor.get_all_providers.return_value = {provider_name: provider}
    accessor.get_enabled_providers.return_value = {provider_name: provider}
    accessor.get_proxy_config.return_value = None
    return accessor


def _mock_db_manager() -> MagicMock:
    """Build a mock DatabaseManager whose keys.sync is an AsyncMock."""
    db = MagicMock(spec=DatabaseManager)
    db.keys = MagicMock()
    db.keys.sync = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test 10.1 — Full cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_and_cleanup_full_cycle(tmp_path):
    """Full cycle: read keys → sync mock DB → cleanup raw files.

    Raw files are deleted after a successful sync with
    ``clean_raw_after_sync=True``.
    """
    provider = "test_provider"
    raw_dir = _make_raw_dir(tmp_path, provider)

    # Create key files
    (raw_dir / "keys.txt").write_text("sk-key1 sk-key2", encoding="utf-8")
    (raw_dir / "extra.ndjson").write_text('{"value": "sk-key3"}\n', encoding="utf-8")

    # Phase 1 — Read keys from directory
    keys, file_map = read_keys_from_directory(str(raw_dir))
    assert keys == {"sk-key1", "sk-key2", "sk-key3"}
    assert len(file_map) == 2

    # Phase 2 — Apply state with mocked sync
    accessor = _mock_accessor(provider)
    db = _mock_db_manager()
    syncer = KeySyncer(accessor, db)

    state: ProviderKeyState = {
        "keys_from_files": keys,
        "models_from_config": ["model-a"],
        "file_map": file_map,
    }
    data_root = str(tmp_path / "data")

    with patch("os.path.join", _patched_os_path_join(data_root)):
        await syncer.apply_state({provider: 1}, {provider: state})

    # DB sync was called
    db.keys.sync.assert_called_once()

    # Raw files deleted after successful sync
    assert not (raw_dir / "keys.txt").exists()
    assert not (raw_dir / "extra.ndjson").exists()


# ---------------------------------------------------------------------------
# Test 10.2 — Sync failure preserves raw files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_failure_preserves_raw_files(tmp_path):
    """KeyRepository.sync() raises an exception — raw files are preserved,
    NOT deleted."""
    provider = "test_provider"
    raw_dir = _make_raw_dir(tmp_path, provider)

    (raw_dir / "keys.txt").write_text("sk-key1 sk-key2", encoding="utf-8")

    # Phase 1 — Read keys
    keys, file_map = read_keys_from_directory(str(raw_dir))
    assert keys == {"sk-key1", "sk-key2"}

    # Phase 2 — Apply state with sync that raises
    accessor = _mock_accessor(provider)
    db = _mock_db_manager()
    db.keys.sync = AsyncMock(side_effect=RuntimeError("DB connection lost"))
    syncer = KeySyncer(accessor, db)

    state: ProviderKeyState = {
        "keys_from_files": keys,
        "models_from_config": ["model-a"],
        "file_map": file_map,
    }
    data_root = str(tmp_path / "data")

    with patch("os.path.join", _patched_os_path_join(data_root)):
        await syncer.apply_state({provider: 1}, {provider: state})

    # Raw files preserved after sync failure
    assert (raw_dir / "keys.txt").exists()
    assert "sk-key1" in (raw_dir / "keys.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 10.3 — mtime changed preserves file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mtime_changed_preserves_file_in_full_cycle(tmp_path, caplog):
    """File modified between read and cleanup — file is preserved and a
    warning is logged."""
    provider = "test_provider"
    raw_dir = _make_raw_dir(tmp_path, provider)

    key_file = raw_dir / "keys.txt"
    key_file.write_text("sk-key1", encoding="utf-8")

    # Phase 1 — Read keys (captures mtime)
    keys, file_map = read_keys_from_directory(str(raw_dir))
    assert keys == {"sk-key1"}
    recorded_mtime = file_map[str(key_file)]

    # Simulate modification: rewrite content and ensure mtime differs
    key_file.write_text("sk-key1 sk-key2 sk-newkey", encoding="utf-8")
    current_mtime = os.stat(str(key_file)).st_mtime
    if current_mtime == recorded_mtime:
        # Coarse-grained filesystem (1 s mtime) — force a visible delta
        os.utime(str(key_file), (recorded_mtime + 5.0, recorded_mtime + 5.0))

    # Phase 2 — Apply state
    accessor = _mock_accessor(provider)
    db = _mock_db_manager()
    syncer = KeySyncer(accessor, db)

    state: ProviderKeyState = {
        "keys_from_files": keys,
        "models_from_config": ["model-a"],
        "file_map": file_map,
    }
    data_root = str(tmp_path / "data")

    with (
        caplog.at_level(logging.WARNING),
        patch("os.path.join", _patched_os_path_join(data_root)),
    ):
        await syncer.apply_state({provider: 1}, {provider: state})

    # File preserved (NOT deleted)
    assert key_file.exists()

    # Warning logged about modified file
    assert "modified since read" in caplog.text


# ---------------------------------------------------------------------------
# Test 10.4 — Startup trash cleanup then normal sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_trash_cleanup_then_normal_sync(tmp_path):
    """.trash/ with leftover files → _setup_directories cleans them →
    a normal sync cycle works afterwards."""
    provider = "test_provider"
    raw_dir = _make_raw_dir(tmp_path, provider)

    # Pre-existing .trash/ with crash leftovers
    trash = raw_dir / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    (trash / "leftover_keys.txt").write_text("old-key", encoding="utf-8")
    (trash / "leftover_keys.ndjson").write_text(
        '{"value": "old-ndjson-key"}\n', encoding="utf-8"
    )
    assert trash.exists()
    assert len(list(trash.iterdir())) == 2

    # Current key files
    (raw_dir / "keys.txt").write_text("sk-active1 sk-active2", encoding="utf-8")

    accessor = _mock_accessor(provider)
    data_root = str(tmp_path / "data")
    join_patch = _patched_os_path_join(data_root)

    # Phase 1 — Startup cleanup via _setup_directories
    with patch("os.path.join", join_patch):
        _setup_directories(accessor)

    # .trash/ cleaned at startup
    assert not trash.exists()

    # Phase 2 — Normal sync cycle
    keys, file_map = read_keys_from_directory(str(raw_dir))
    assert keys == {"sk-active1", "sk-active2"}

    db = _mock_db_manager()
    syncer = KeySyncer(accessor, db)

    state: ProviderKeyState = {
        "keys_from_files": keys,
        "models_from_config": ["model-a"],
        "file_map": file_map,
    }

    with patch("os.path.join", join_patch):
        await syncer.apply_state({provider: 1}, {provider: state})

    # DB sync was called
    db.keys.sync.assert_called_once()

    # Raw files cleaned up after successful sync
    assert not (raw_dir / "keys.txt").exists()
