"""Tests for _setup_directories trash cleanup in background_worker.py (Group 7)."""

import logging
from unittest.mock import MagicMock

from src.services.background_worker import _setup_directories


def test_setup_directories_cleans_trash_with_leftover_files(
    tmp_path, monkeypatch, caplog
):
    """raw/.trash/ has leftover files, all deleted and dir removed."""
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)

    # Create .trash/ with leftover files from a previous crash
    trash_dir = tmp_path / "data" / "test-provider" / "raw" / ".trash"
    trash_dir.mkdir(parents=True)
    (trash_dir / "key1.txt").write_text("sk-xxx")
    (trash_dir / "key2.txt").write_text("sk-yyy")

    # Place a valid key file in raw/ so the "no key files" warning is not emitted
    raw_dir = tmp_path / "data" / "test-provider" / "raw"
    (raw_dir / "valid_key.txt").write_text("sk-valid")

    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    _setup_directories(mock_accessor)

    # All files inside .trash/ should be gone and the directory itself removed
    assert not trash_dir.exists()
    assert "removed leftover .trash/" in caplog.text


def test_setup_directories_no_trash_dir_no_error(tmp_path, monkeypatch, caplog):
    """raw/.trash/ doesn't exist, no error."""
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)

    # Create raw/ with a key file but NO .trash/
    raw_dir = tmp_path / "data" / "test-provider" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "valid_key.txt").write_text("sk-valid")

    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    _setup_directories(mock_accessor)

    # No error raised and no cleanup log message
    assert "removed leftover .trash/" not in caplog.text


def test_setup_directories_trash_cleanup_for_each_provider(
    tmp_path, monkeypatch, caplog
):
    """Multiple providers with .trash/, cleanup for each."""
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)

    providers = {}
    for name in ("provider-a", "provider-b", "provider-c"):
        # Create .trash/ for each provider
        trash_dir = tmp_path / "data" / name / "raw" / ".trash"
        trash_dir.mkdir(parents=True)
        (trash_dir / f"{name}_key.txt").write_text("sk-trash")

        # Also a valid key in raw/ to suppress the "no key files" warning
        raw_dir = tmp_path / "data" / name / "raw"
        (raw_dir / "valid_key.txt").write_text("sk-valid")

        mock_provider = MagicMock()
        mock_provider.enabled = True
        providers[name] = mock_provider

    mock_accessor = MagicMock()
    mock_accessor.get_all_providers.return_value = providers
    mock_accessor.get_proxy_config.return_value = None

    _setup_directories(mock_accessor)

    # Verify all .trash/ directories are gone
    for name in ("provider-a", "provider-b", "provider-c"):
        trash_dir = tmp_path / "data" / name / "raw" / ".trash"
        assert not trash_dir.exists()

    # Verify cleanup was logged for each provider
    for name in ("provider-a", "provider-b", "provider-c"):
        assert name in caplog.text


def test_setup_directories_trash_cleanup_preserves_raw_files(
    tmp_path, monkeypatch, caplog
):
    """Only .trash/ removed, normal raw files preserved."""
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)

    # Create raw/ with normal key files AND .trash/
    raw_dir = tmp_path / "data" / "test-provider" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "key1.txt").write_text("sk-key1")
    (raw_dir / "key2.ndjson").write_text('{"key": "sk-key2"}')

    trash_dir = raw_dir / ".trash"
    trash_dir.mkdir()
    (trash_dir / "old_key.txt").write_text("sk-old")

    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    _setup_directories(mock_accessor)

    # .trash/ should be gone
    assert not trash_dir.exists()
    # Normal raw files should still exist
    assert (raw_dir / "key1.txt").exists()
    assert (raw_dir / "key2.ndjson").exists()


def test_setup_directories_trash_cleanup_empty_trash_dir(tmp_path, monkeypatch, caplog):
    """.trash/ exists but empty, directory removed."""
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)

    # Create empty .trash/
    trash_dir = tmp_path / "data" / "test-provider" / "raw" / ".trash"
    trash_dir.mkdir(parents=True)

    # Place a valid key file in raw/ to suppress the "no key files" warning
    raw_dir = tmp_path / "data" / "test-provider" / "raw"
    (raw_dir / "valid_key.txt").write_text("sk-valid")

    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    _setup_directories(mock_accessor)

    # .trash/ should be removed even though it was empty
    assert not trash_dir.exists()
    # Cleanup should be logged
    assert "removed leftover .trash/" in caplog.text
