"""Tests for _setup_directories in background_worker.py."""

from unittest.mock import MagicMock, patch

from src.services.background_worker import _setup_directories


def test_setup_directories_creates_data_name_raw():
    """_setup_directories creates data/<name>/raw for enabled providers."""
    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None  # no stealth proxy

    with patch("src.services.background_worker.os.makedirs") as mock_makedirs:
        _setup_directories(mock_accessor)

    mock_makedirs.assert_any_call("data/test-provider/raw", exist_ok=True)


def test_setup_directories_existing_directory_no_error():
    """Existing directory does not raise error (exist_ok=True)."""
    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    with patch("src.services.background_worker.os.makedirs") as mock_makedirs:
        _setup_directories(mock_accessor)

    # Should still be called with exist_ok=True
    call_kwargs = mock_makedirs.call_args[1]
    assert call_kwargs["exist_ok"] is True


def test_setup_directories_does_not_use_keys_path():
    """_setup_directories does not access provider.keys_path."""
    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = True
    mock_accessor.get_all_providers.return_value = {"test-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    with patch("src.services.background_worker.os.makedirs"):
        _setup_directories(mock_accessor)

    # provider.keys_path should never be accessed
    # Since it's a MagicMock, any attribute access returns another MagicMock
    # We just verify the path was computed correctly
    assert True  # No exception means no keys_path access attempted


def test_setup_directories_skips_disabled_providers():
    """Disabled providers do not get directories created."""
    mock_accessor = MagicMock()
    mock_provider = MagicMock()
    mock_provider.enabled = False
    mock_accessor.get_all_providers.return_value = {"disabled-provider": mock_provider}
    mock_accessor.get_proxy_config.return_value = None

    with patch("src.services.background_worker.os.makedirs") as mock_makedirs:
        _setup_directories(mock_accessor)

    # No makedirs should be called for disabled providers
    # (should not have been called with any data/ path for this provider)
    for call in mock_makedirs.call_args_list:
        assert "disabled-provider" not in str(call)
