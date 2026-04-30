#!/usr/bin/env python3

"""
Unit tests for DatabasePoolConfig schema.

Tests cover defaults, validation, bounds checking, YAML loading via
ConfigLoader, and security-related edge cases.

Test IDs:
  UT-P01..UT-P09  — Functional tests for DatabasePoolConfig
  SEC-03, SEC-04   — Security: bounds / zero-value rejection
  SEC-06           — Security: unknown-field handling in pool sub-model
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    Config,
    DatabaseConfig,
    DatabasePoolConfig,
    VacuumPolicyConfig,
)

# ==============================================================================
# UT-P01..UT-P04: Default values and basic construction
# ==============================================================================


class TestDatabasePoolConfigDefaults:
    """Test DatabasePoolConfig default values and basic construction."""

    def test_ut_p01_default_values(self):
        """UT-P01: DatabasePoolConfig() → min_size=1, max_size=15."""
        pool = DatabasePoolConfig()
        assert pool.min_size == 1
        assert pool.max_size == 15

    def test_ut_p02_custom_values(self):
        """UT-P02: DatabasePoolConfig(min_size=2, max_size=10) → values match."""
        pool = DatabasePoolConfig(min_size=2, max_size=10)
        assert pool.min_size == 2
        assert pool.max_size == 10

    def test_ut_p04_equal_min_max_valid(self):
        """UT-P04: DatabasePoolConfig(min_size=5, max_size=5) → valid (equal values allowed)."""
        pool = DatabasePoolConfig(min_size=5, max_size=5)
        assert pool.min_size == 5
        assert pool.max_size == 5


# ==============================================================================
# UT-P03, UT-P05, UT-P06: Validation errors
# ==============================================================================


class TestDatabasePoolConfigValidation:
    """Test DatabasePoolConfig validation error scenarios."""

    def test_ut_p03_min_exceeds_max(self):
        """UT-P03: DatabasePoolConfig(min_size=20, max_size=5) → raises ValidationError,
        error message contains 'min_size' and 'max_size' (from check_bounds validator).
        """
        with pytest.raises(ValidationError) as exc_info:
            DatabasePoolConfig(min_size=20, max_size=5)

        error_message = str(exc_info.value)
        assert "min_size" in error_message
        assert "max_size" in error_message

    def test_ut_p05_min_size_zero(self):
        """UT-P05: DatabasePoolConfig(min_size=0) → raises ValidationError,
        error contains gt=0 constraint information.
        """
        with pytest.raises(ValidationError) as exc_info:
            DatabasePoolConfig(min_size=0)

        error_message = str(exc_info.value)
        assert "min_size" in error_message
        # Pydantic v2 reports gt=0 as "Input should be greater than 0"
        assert "greater than 0" in error_message

    def test_ut_p06_max_size_zero(self):
        """UT-P06: DatabasePoolConfig(max_size=0) → raises ValidationError,
        error contains gt=0 constraint information.
        """
        with pytest.raises(ValidationError) as exc_info:
            DatabasePoolConfig(max_size=0)

        error_message = str(exc_info.value)
        assert "max_size" in error_message
        assert "greater than 0" in error_message


# ==============================================================================
# UT-P07: Integration with root Config
# ==============================================================================


class TestDatabasePoolConfigInRootConfig:
    """Test DatabasePoolConfig integration with the root Config object."""

    def test_ut_p07_config_database_pool_defaults(self):
        """UT-P07: Config() → config.database.pool exists and is DatabasePoolConfig
        with default min_size=1, max_size=15.
        """
        config = Config()
        assert hasattr(config, "database")
        assert hasattr(config.database, "pool")
        assert isinstance(config.database.pool, DatabasePoolConfig)
        assert config.database.pool.min_size == 1
        assert config.database.pool.max_size == 15


# ==============================================================================
# UT-P08, UT-P09: YAML loading via ConfigLoader
# ==============================================================================


class TestDatabasePoolConfigYamlLoading:
    """Test DatabasePoolConfig loading through ConfigLoader with YAML content."""

    def test_ut_p08_yaml_without_pool_section(self):
        """UT-P08: YAML with database: {host: "localhost"} without pool →
        ConfigLoader applies pool defaults (min_size=1, max_size=15).
        """
        yaml_content = """database:
  host: localhost
  password: test_password
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            # Pool defaults should be applied when no pool section in YAML
            assert config.database.pool.min_size == 1
            assert config.database.pool.max_size == 15

    def test_ut_p09_yaml_with_pool_section(self):
        """UT-P09: YAML with database: {host: "localhost", pool: {min_size: 2, max_size: 12}} →
        ConfigLoader loads pool values correctly.
        """
        yaml_content = """database:
  host: localhost
  password: test_password
  pool:
    min_size: 2
    max_size: 12
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.database.pool.min_size == 2
            assert config.database.pool.max_size == 12


# ==============================================================================
# SEC-03, SEC-04, SEC-06: Security validation tests
# ==============================================================================


class TestDatabasePoolConfigSecurity:
    """Security-related validation tests for DatabasePoolConfig."""

    def test_sec_03_min_exceeds_max_raises_validation_error(self):
        """SEC-03: DatabasePoolConfig(min_size=20, max_size=5) → ValidationError
        (bounds violation rejected at model level).
        """
        with pytest.raises(ValidationError):
            DatabasePoolConfig(min_size=20, max_size=5)

    def test_sec_04_max_size_zero_raises_validation_error(self):
        """SEC-04: DatabasePoolConfig(max_size=0) → ValidationError
        (zero value rejected by gt=0 constraint).
        """
        with pytest.raises(ValidationError):
            DatabasePoolConfig(max_size=0)

    def test_sec_06_unknown_field_in_pool_silently_ignored(self):
        """SEC-06: Unknown field in pool section is silently ignored, NOT rejected.

            DatabasePoolConfig does NOT have extra='forbid', so unknown fields
            are silently dropped rather than raising ValidationError. The root
            Config has extra='forbid' but this only applies to top-level keys,
            not to nested sub-models like DatabasePoolConfig.

            This test documents the current behavior: unknown pool fields are
            ignored without error, which could be a concern if misconfiguration
        goes undetected.
        """
        # Via Config.model_validate: unknown field in pool is silently ignored
        # (not rejected, since DatabasePoolConfig doesn't have extra="forbid")
        config = Config.model_validate(
            {
                "database": {
                    "pool": {
                        "min_size": 3,
                        "max_size": 10,
                        "unknown_field": 1,
                    },
                },
            }
        )
        assert config.database.pool.min_size == 3
        assert config.database.pool.max_size == 10
        # unknown_field is silently dropped — not stored, not rejected


# ==============================================================================
# M8..M11: DatabaseConfig — vacuum_policy default factory and YAML override
# ==============================================================================


def test_database_config_vacuum_policy_default_factory():
    """M8: DatabaseConfig() → vacuum_policy is VacuumPolicyConfig with defaults."""
    db_config = DatabaseConfig()
    assert isinstance(db_config.vacuum_policy, VacuumPolicyConfig)
    assert db_config.vacuum_policy.interval_minutes == 60
    assert db_config.vacuum_policy.dead_tuple_ratio_threshold == 0.3


def test_database_config_vacuum_policy_always_present():
    """M9: vacuum_policy is not None and is an instance of VacuumPolicyConfig."""
    db_config = DatabaseConfig()
    assert db_config.vacuum_policy is not None
    assert isinstance(db_config.vacuum_policy, VacuumPolicyConfig)


def test_database_config_vacuum_policy_yaml_override():
    """M10: YAML with database.vacuum_policy.interval_minutes: 30 → interval_minutes == 30."""
    yaml_content = """database:
  host: localhost
  password: test_password
  vacuum_policy:
    interval_minutes: 30
"""
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()

        assert config.database.vacuum_policy.interval_minutes == 30


def test_database_config_vacuum_policy_yaml_without_section():
    """M11: YAML without vacuum_policy section → defaults apply (60, 0.3)."""
    yaml_content = """database:
  host: localhost
  password: test_password
"""
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()

        assert config.database.vacuum_policy.interval_minutes == 60
        assert config.database.vacuum_policy.dead_tuple_ratio_threshold == 0.3
