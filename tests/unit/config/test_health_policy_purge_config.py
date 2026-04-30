#!/usr/bin/env python3

"""
Test suite for PurgeConfig schema and its integration with HealthPolicyConfig.

Tests cover defaults, validation, bounds checking, YAML loading via
ConfigLoader, and integration with HealthPolicyConfig's default_factory.

Test IDs:
  N31..N36  — Functional tests for PurgeConfig and HealthPolicyConfig integration
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import HealthPolicyConfig, PurgeConfig

# ==============================================================================
# N31..N33: PurgeConfig — defaults and field validation
# ==============================================================================


def test_purge_config_default_after_days():
    """N31: PurgeConfig() → after_days == 180 (default)."""
    config = PurgeConfig()
    assert config.after_days == 180


def test_purge_config_custom_after_days():
    """N32: PurgeConfig(after_days=365) → after_days == 365."""
    config = PurgeConfig(after_days=365)
    assert config.after_days == 365


def test_purge_config_after_days_ge_1():
    """N33: PurgeConfig(after_days=0) → ValidationError (ge=1 constraint)."""
    with pytest.raises(ValidationError) as exc_info:
        PurgeConfig(after_days=0)

    error_message = str(exc_info.value)
    assert "after_days" in error_message


# ==============================================================================
# N34: PurgeConfig — no enabled field
# ==============================================================================


def test_purge_config_no_enabled_field():
    """N34: PurgeConfig(enabled=False) → ValidationError.

    PurgeConfig does not have an 'enabled' field. If PurgeConfig has
    extra='forbid', this raises ValidationError. If it does not, the
    field is silently ignored and the test documents the gap.
    """
    with pytest.raises(ValidationError) as exc_info:
        PurgeConfig(enabled=False)

    error_message = str(exc_info.value)
    assert "enabled" in error_message


# ==============================================================================
# N35: PurgeConfig — default factory in HealthPolicyConfig
# ==============================================================================


def test_purge_config_in_health_policy_default_factory():
    """N35: HealthPolicyConfig().purge is a PurgeConfig instance with after_days=180."""
    policy = HealthPolicyConfig()
    assert isinstance(policy.purge, PurgeConfig)
    assert policy.purge.after_days == 180


# ==============================================================================
# N36: PurgeConfig — YAML override
# ==============================================================================


def test_purge_config_yaml_override():
    """N36: YAML with purge.after_days: 365 → purge.after_days == 365."""
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    worker_health_policy:
      purge:
        after_days: 365
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.worker_health_policy.purge.after_days == 365
