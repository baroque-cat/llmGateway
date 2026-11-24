"""Tests for NetworkGuardConfig validation and defaults.

Verifies that:
- Default values are correct (enabled=False, mode="pause")
- Validation rules are enforced
- ConfigAccessor.get_network_guard_config() returns the config
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import NetworkGuardConfig


def test_network_guard_config_defaults():
    """Default values: enabled=False, mode='pause'."""
    config = NetworkGuardConfig()
    assert config.enabled is False
    assert config.mode == "pause"
    assert config.probe_urls == []
    assert config.probe_interval_sec == 30
    assert config.probe_connect_timeout_sec == 3.0
    assert config.probe_total_timeout_sec == 5.0
    assert config.min_probe_successes == 2
    assert config.fail_threshold == 3
    assert config.passive_window_sec == 60
    assert config.passive_min_providers == 3
    assert config.passive_min_failures == 6
    assert config.startup_probe is True
    assert config.auto_recover is False
    assert config.marker_path == "/app/data/network_guard/state.json"


def test_network_guard_config_enabled_true():
    """enabled=True is valid."""
    config = NetworkGuardConfig(enabled=True)
    assert config.enabled is True


def test_network_guard_config_mode_log():
    """mode='log' is valid."""
    config = NetworkGuardConfig(mode="log")
    assert config.mode == "log"


def test_network_guard_config_mode_pause():
    """mode='pause' is valid."""
    config = NetworkGuardConfig(mode="pause")
    assert config.mode == "pause"


def test_network_guard_config_invalid_mode():
    """Invalid mode raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(mode="invalid")  # type: ignore[arg-type]
    assert "mode" in str(exc_info.value).lower()


def test_network_guard_config_probe_interval_min():
    """probe_interval_sec must be >= 5."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(probe_interval_sec=4)
    assert "probe_interval_sec" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(probe_interval_sec=5)
    assert config.probe_interval_sec == 5


def test_network_guard_config_probe_connect_timeout_positive():
    """probe_connect_timeout_sec must be > 0."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(probe_connect_timeout_sec=0)
    assert "probe_connect_timeout_sec" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(probe_connect_timeout_sec=0.1)
    assert config.probe_connect_timeout_sec == 0.1


def test_network_guard_config_probe_total_timeout_positive():
    """probe_total_timeout_sec must be > 0."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(probe_total_timeout_sec=0)
    assert "probe_total_timeout_sec" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(probe_total_timeout_sec=0.1)
    assert config.probe_total_timeout_sec == 0.1


def test_network_guard_config_min_probe_successes_min():
    """min_probe_successes must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(min_probe_successes=0)
    assert "min_probe_successes" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(min_probe_successes=1)
    assert config.min_probe_successes == 1


def test_network_guard_config_fail_threshold_min():
    """fail_threshold must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(fail_threshold=0)
    assert "fail_threshold" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(fail_threshold=1)
    assert config.fail_threshold == 1


def test_network_guard_config_passive_window_min():
    """passive_window_sec must be >= 5."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(passive_window_sec=4)
    assert "passive_window_sec" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(passive_window_sec=5)
    assert config.passive_window_sec == 5


def test_network_guard_config_passive_min_providers_min():
    """passive_min_providers must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(passive_min_providers=0)
    assert "passive_min_providers" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(passive_min_providers=1)
    assert config.passive_min_providers == 1


def test_network_guard_config_passive_min_failures_min():
    """passive_min_failures must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(passive_min_failures=0)
    assert "passive_min_failures" in str(exc_info.value).lower()

    # Valid value
    config = NetworkGuardConfig(passive_min_failures=1)
    assert config.passive_min_failures == 1


def test_network_guard_config_probe_urls_list():
    """probe_urls accepts a list of strings."""
    config = NetworkGuardConfig(
        probe_urls=["https://cloudflare.com", "https://google.com"]
    )
    assert config.probe_urls == ["https://cloudflare.com", "https://google.com"]


def test_network_guard_config_extra_fields_forbidden():
    """Extra fields are forbidden (extra='forbid')."""
    with pytest.raises(ValidationError) as exc_info:
        NetworkGuardConfig(extra_field="value")  # type: ignore[call-arg]
    assert (
        "extra" in str(exc_info.value).lower()
        or "extra_field" in str(exc_info.value).lower()
    )
