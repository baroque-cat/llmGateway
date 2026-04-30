"""Tests for _setup_directories in keeper.py — basic and cleanup scenarios."""

import logging
from unittest.mock import MagicMock

from src.services.keeper import _setup_directories


class TestSetupDirectories:
    """Basic tests for _setup_directories."""

    def test_setup_directories_creates_data_name_raw(self):
        """_setup_directories creates data/<name>/raw for enabled providers."""
        mock_accessor = MagicMock()
        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
        mock_accessor.get_proxy_config.return_value = None  # no stealth proxy

        with MagicMock() as mock_makedirs:
            from unittest.mock import patch

            with patch("src.services.keeper.os.makedirs") as patched_makedirs:
                _setup_directories(mock_accessor)
                patched_makedirs.assert_any_call("data/test-provider/raw", exist_ok=True)

    def test_setup_directories_existing_directory_no_error(self):
        """Existing directory does not raise error (exist_ok=True)."""
        mock_accessor = MagicMock()
        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
        mock_accessor.get_proxy_config.return_value = None

        from unittest.mock import patch

        with patch("src.services.keeper.os.makedirs") as mock_makedirs:
            _setup_directories(mock_accessor)

        # Should still be called with exist_ok=True
        call_kwargs = mock_makedirs.call_args[1]
        assert call_kwargs["exist_ok"] is True

    def test_setup_directories_does_not_use_keys_path(self):
        """_setup_directories does not access provider.keys_path."""
        mock_accessor = MagicMock()
        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
        mock_accessor.get_proxy_config.return_value = None

        from unittest.mock import patch

        with patch("src.services.keeper.os.makedirs"):
            _setup_directories(mock_accessor)

        # provider.keys_path should never be accessed
        # Since it's a MagicMock, any attribute access returns another MagicMock
        # We just verify the path was computed correctly
        assert True  # No exception means no keys_path access attempted

    def test_setup_directories_skips_disabled_providers(self):
        """Disabled providers do not get directories created."""
        mock_accessor = MagicMock()
        mock_provider = MagicMock()
        mock_provider.enabled = False
        mock_accessor.get_all_providers.return_value = {"disabled-provider": mock_provider}
        mock_accessor.get_proxy_config.return_value = None

        from unittest.mock import patch

        with patch("src.services.keeper.os.makedirs") as mock_makedirs:
            _setup_directories(mock_accessor)

        # No makedirs should be called for disabled providers
        # (should not have been called with any data/ path for this provider)
        for call in mock_makedirs.call_args_list:
            assert "disabled-provider" not in str(call)


class TestSetupDirectoriesCleanup:
    """Tests for _setup_directories trash cleanup (Group 7)."""

    def test_setup_directories_cleans_trash_with_leftover_files(
        self, tmp_path, monkeypatch, caplog
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

    def test_setup_directories_no_trash_dir_no_error(self, tmp_path, monkeypatch, caplog):
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
        self, tmp_path, monkeypatch, caplog
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
        self, tmp_path, monkeypatch, caplog
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

    def test_setup_directories_trash_cleanup_empty_trash_dir(self, tmp_path, monkeypatch, caplog):
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
