#!/usr/bin/env python3

"""
Test suite for ProxyMode enum and ProxyConfig validation.

Group G3 tests: ProxyMode StrEnum members, ProxyConfig schema validation,
                 cross-field validator (validate_proxy_requirements) with enum,
                 and YAML loading integration for proxy mode.

Covers 11 scenarios from the test plan for the 'harden-config-validation' change.
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import ProxyConfig
from src.core.constants import ProxyMode

# ==============================================================================
# G3-1: ProxyMode enum structure
# ==============================================================================


def test_proxy_mode_enum_members():
    """
    ProxyMode enum has exactly three members: NONE, STATIC, STEALTH
    with string values 'none', 'static', 'stealth'.
    """
    members = list(ProxyMode)
    assert len(members) == 3
    assert members == [ProxyMode.NONE, ProxyMode.STATIC, ProxyMode.STEALTH]
    assert ProxyMode.NONE.value == "none"
    assert ProxyMode.STATIC.value == "static"
    assert ProxyMode.STEALTH.value == "stealth"


# ==============================================================================
# G3-2..G3-5: ProxyConfig direct schema validation
# ==============================================================================


def test_proxy_config_valid_mode_none():
    """
    ProxyConfig(mode='none') should coerce the string to ProxyMode.NONE.
    """
    config = ProxyConfig(mode="none")
    assert config.mode == ProxyMode.NONE


def test_proxy_config_valid_mode_static_with_url():
    """
    ProxyConfig(mode='static', static_url='http://proxy:8080') should
    coerce mode to ProxyMode.STATIC and accept the URL.
    """
    config = ProxyConfig(mode="static", static_url="http://proxy:8080")
    assert config.mode == ProxyMode.STATIC
    assert config.static_url == "http://proxy:8080"


def test_proxy_config_valid_mode_stealth_with_pool_path():
    """
    ProxyConfig(mode='stealth', pool_list_path='/pools/') should
    coerce mode to ProxyMode.STEALTH and accept the pool path.
    """
    config = ProxyConfig(mode="stealth", pool_list_path="/pools/")
    assert config.mode == ProxyMode.STEALTH
    assert config.pool_list_path == "/pools/"


def test_proxy_config_invalid_mode_rejected():
    """
    ProxyConfig(mode='sttaic') should raise ValidationError.
    The error message must list valid values: 'none', 'static', 'stealth'.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="sttaic")

    error_message = str(exc_info.value)
    # Pydantic v2 lists valid enum values in the error message
    assert "none" in error_message
    assert "static" in error_message
    assert "stealth" in error_message


# ==============================================================================
# G3-6..G3-7: ProxyConfig defaults and StrEnum string compatibility
# ==============================================================================


def test_proxy_config_default_mode_is_none():
    """
    ProxyConfig() without specifying mode should default to ProxyMode.NONE.
    """
    config = ProxyConfig()
    assert config.mode == ProxyMode.NONE


def test_proxy_config_mode_string_comparison_works():
    """
    ProxyMode is a StrEnum, so ProxyMode.STEALTH == 'stealth' must be True.
    This ensures backward compatibility with string-based comparisons.
    """
    config = ProxyConfig(mode="stealth", pool_list_path="/p/")
    assert config.mode == "stealth"
    assert config.mode == ProxyMode.STEALTH


# ==============================================================================
# G3-8..G3-9: Cross-field validator (validate_proxy_requirements) with enum
# ==============================================================================


def test_proxy_config_static_mode_requires_url_with_enum():
    """
    ProxyConfig(mode='static') without static_url should raise ValidationError
    because the cross-field validator validate_proxy_requirements checks
    that static mode requires a URL. The validator works with ProxyMode enum.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="static")

    error_message = str(exc_info.value)
    assert "static_url" in error_message


def test_proxy_config_stealth_mode_requires_pool_path_with_enum():
    """
    ProxyConfig(mode='stealth') without pool_list_path should raise ValidationError
    because the cross-field validator validate_proxy_requirements checks
    that stealth mode requires a pool path. The validator works with ProxyMode enum.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="stealth")

    error_message = str(exc_info.value)
    assert "pool_list_path" in error_message


# ==============================================================================
# G3-10..G3-11: YAML loading integration tests for proxy mode
# ==============================================================================


def test_proxy_mode_yaml_typo_causes_system_exit():
    """
    YAML config with a typo in proxy_config.mode ('sttaic') should cause
    SystemExit when loaded through ConfigLoader, because Pydantic rejects
    the invalid enum value and handle_validation_error calls sys.exit(1).
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "anthropic"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    proxy_config:
      mode: "sttaic"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_proxy_mode_yaml_valid_stealth_loads():
    """
    YAML config with proxy_config: {mode: 'stealth', pool_list_path: '/p/'}
    should load successfully through ConfigLoader, and the resulting
    proxy_config.mode should be ProxyMode.STEALTH.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "anthropic"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    proxy_config:
      mode: "stealth"
      pool_list_path: "/p/"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.proxy_config.mode == ProxyMode.STEALTH
        assert provider.proxy_config.pool_list_path == "/p/"
