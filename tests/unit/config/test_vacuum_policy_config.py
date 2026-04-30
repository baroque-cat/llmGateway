#!/usr/bin/env python3

"""
Test suite for VacuumPolicyConfig schema and its integration with DatabaseConfig.

Tests cover defaults, validation, bounds checking, YAML loading via
ConfigLoader, and integration with DatabaseConfig's default_factory.

Test IDs:
  N37..N44  — Functional tests for VacuumPolicyConfig and DatabaseConfig integration
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import DatabaseConfig, VacuumPolicyConfig

# ==============================================================================
# N37..N40: VacuumPolicyConfig — defaults and field validation
# ==============================================================================


def test_vacuum_policy_config_defaults():
    """N37: VacuumPolicyConfig() → interval_minutes == 60, dead_tuple_ratio_threshold == 0.3."""
    config = VacuumPolicyConfig()
    assert config.interval_minutes == 60
    assert config.dead_tuple_ratio_threshold == 0.3


def test_vacuum_policy_config_custom_values():
    """N38: VacuumPolicyConfig(interval_minutes=30, dead_tuple_ratio_threshold=0.5) → values match."""
    config = VacuumPolicyConfig(interval_minutes=30, dead_tuple_ratio_threshold=0.5)
    assert config.interval_minutes == 30
    assert config.dead_tuple_ratio_threshold == 0.5


def test_vacuum_policy_config_interval_minutes_gt_0():
    """N39: VacuumPolicyConfig(interval_minutes=0) → ValidationError (ge=1 constraint)."""
    with pytest.raises(ValidationError) as exc_info:
        VacuumPolicyConfig(interval_minutes=0)

    error_message = str(exc_info.value)
    assert "interval_minutes" in error_message


def test_vacuum_policy_config_threshold_range():
    """N40: VacuumPolicyConfig(dead_tuple_ratio_threshold=1.5) → ValidationError.

    The threshold must be strictly between 0.0 and 1.0 (gt=0.0, lt=1.0).
    """
    with pytest.raises(ValidationError) as exc_info:
        VacuumPolicyConfig(dead_tuple_ratio_threshold=1.5)

    error_message = str(exc_info.value)
    assert "dead_tuple_ratio_threshold" in error_message


# ==============================================================================
# N41: VacuumPolicyConfig — no enabled field
# ==============================================================================


def test_vacuum_policy_config_no_enabled_field():
    """N41: VacuumPolicyConfig(enabled=False) → ValidationError.

    VacuumPolicyConfig does not have an 'enabled' field. If VacuumPolicyConfig
    has extra='forbid', this raises ValidationError. If it does not, the
    field is silently ignored and the test documents the gap.
    """
    with pytest.raises(ValidationError) as exc_info:
        VacuumPolicyConfig(enabled=False)

    error_message = str(exc_info.value)
    assert "enabled" in error_message


# ==============================================================================
# N42: VacuumPolicyConfig — default factory in DatabaseConfig
# ==============================================================================


def test_vacuum_policy_config_in_database_config_default_factory():
    """N42: DatabaseConfig().vacuum_policy is VacuumPolicyConfig with defaults."""
    db_config = DatabaseConfig()
    assert isinstance(db_config.vacuum_policy, VacuumPolicyConfig)
    assert db_config.vacuum_policy.interval_minutes == 60
    assert db_config.vacuum_policy.dead_tuple_ratio_threshold == 0.3


# ==============================================================================
# N43..N44: VacuumPolicyConfig — YAML override and defaults
# ==============================================================================


def test_vacuum_policy_config_yaml_override():
    """N43: YAML with vacuum_policy.interval_minutes: 30 → interval_minutes == 30."""
    mock_yaml_content = """database:
  host: localhost
  password: test_password
  vacuum_policy:
    interval_minutes: 30
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()

        assert config.database.vacuum_policy.interval_minutes == 30


def test_vacuum_policy_config_yaml_without_section_defaults():
    """N44: YAML without vacuum_policy section → defaults apply (60, 0.3)."""
    mock_yaml_content = """database:
  host: localhost
  password: test_password
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()

        assert config.database.vacuum_policy.interval_minutes == 60
        assert config.database.vacuum_policy.dead_tuple_ratio_threshold == 0.3
