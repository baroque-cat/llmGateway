#!/usr/bin/env python3

"""
Unit tests for TimeoutConfig schema validation and YAML loading.

Covers the new ``total`` field (default 600.0, constraint ``gt=0``), updated
defaults for ``connect``, ``read``, ``write``, ``pool``, backward compatibility
for configs that omit the ``total`` field, and YAML round-trip loading via
``ConfigLoader``.

Scenarios from test-plan:
  Scenario #5  — Default total timeout is 600 seconds
  Scenario #6  — Custom total timeout from YAML
  Edge Cases  — total=0 / total=-1 rejection, backward compatibility

Test IDs:
  UT-TC01..UT-TC10  — Functional tests for TimeoutConfig
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    ProviderConfig,
    TimeoutConfig,
)

# ==============================================================================
# UT-TC01..UT-TC02: Default values
# ==============================================================================


class TestTimeoutConfigDefaults:
    """Test TimeoutConfig default values for all fields."""

    def test_ut_tc01_all_default_values(self):
        """
        UT-TC01: TimeoutConfig() returns all defaults as specified.

        connect=10.0, read=120.0, write=20.0, pool=15.0, total=600.0.
        """
        timeouts = TimeoutConfig()
        assert timeouts.connect == 10.0
        assert timeouts.read == 120.0
        assert timeouts.write == 20.0
        assert timeouts.pool == 15.0
        assert timeouts.total == 600.0

    def test_ut_tc02_default_total_timeout_is_600(self):
        """
        Scenario #5: Default total timeout is 600 seconds.

        WHEN a provider omits the ``timeouts`` section from its config,
        THEN ``provider_config.timeouts.total`` SHALL be ``600.0``.

        This is tested via ProviderConfig default_factory — when no
        timeouts are specified, the default TimeoutConfig() is used.
        """
        provider = ProviderConfig(provider_type="openai_like")
        assert isinstance(provider.timeouts, TimeoutConfig)
        assert provider.timeouts.total == 600.0

    def test_ut_tc03_partial_override_preserves_unset_defaults(self):
        """
        Partially overriding some TimeoutConfig fields preserves defaults
        for the remaining fields (including total).
        """
        timeouts = TimeoutConfig(connect=5.0, read=30.0)
        assert timeouts.connect == 5.0
        assert timeouts.read == 30.0
        assert timeouts.write == 20.0  # default preserved
        assert timeouts.pool == 15.0  # default preserved
        assert timeouts.total == 600.0  # default preserved


# ==============================================================================
# UT-TC04..UT-TC05: Custom values
# ==============================================================================


class TestTimeoutConfigCustomValues:
    """Test TimeoutConfig with explicitly provided values."""

    def test_ut_tc04_custom_total_value(self):
        """
        Custom total=300.0 overrides the default of 600.0.
        """
        timeouts = TimeoutConfig(total=300.0)
        assert timeouts.total == 300.0
        # Other defaults remain intact
        assert timeouts.connect == 10.0
        assert timeouts.read == 120.0

    def test_ut_tc05_all_fields_custom_values(self):
        """
        All TimeoutConfig fields can be set to explicit values.
        """
        timeouts = TimeoutConfig(
            connect=3.0,
            read=60.0,
            write=5.0,
            pool=2.0,
            total=120.0,
        )
        assert timeouts.connect == 3.0
        assert timeouts.read == 60.0
        assert timeouts.write == 5.0
        assert timeouts.pool == 2.0
        assert timeouts.total == 120.0


# ==============================================================================
# UT-TC06..UT-TC07: Validation — total field gt=0 constraint
# ==============================================================================


class TestTimeoutConfigValidation:
    """Test TimeoutConfig validation for invalid values."""

    def test_ut_tc06_total_zero_rejected(self):
        """
        Edge case: total=0 is rejected by Pydantic because the field
        constraint is ``gt=0`` (greater than 0, strictly).

        Pydantic v2 reports the constraint as "Input should be greater than 0".
        """
        with pytest.raises(ValidationError) as exc_info:
            TimeoutConfig(total=0)

        error_message = str(exc_info.value)
        assert "total" in error_message
        assert "greater than 0" in error_message

    def test_ut_tc07_total_negative_rejected(self):
        """
        Edge case: total=-1 is rejected by Pydantic because the field
        constraint is ``gt=0``.

        Pydantic v2 reports the constraint as "Input should be greater than 0".
        """
        with pytest.raises(ValidationError) as exc_info:
            TimeoutConfig(total=-1)

        error_message = str(exc_info.value)
        assert "total" in error_message
        assert "greater than 0" in error_message

    def test_ut_tc08_total_float_one_is_valid(self):
        """
        Borderline valid case: total=1.0 meets the gt=0 constraint and
        should be accepted.
        """
        timeouts = TimeoutConfig(total=1.0)
        assert timeouts.total == 1.0

    def test_ut_tc09_connect_zero_rejected(self):
        """
        All TimeoutConfig fields have gt=0 constraint.
        connect=0 should be rejected.
        """
        with pytest.raises(ValidationError) as exc_info:
            TimeoutConfig(connect=0)

        error_message = str(exc_info.value)
        assert "connect" in error_message
        assert "greater than 0" in error_message

    def test_ut_tc10_read_zero_rejected(self):
        """
        read=0 should be rejected by gt=0 constraint.
        """
        with pytest.raises(ValidationError) as exc_info:
            TimeoutConfig(read=0)

        error_message = str(exc_info.value)
        assert "read" in error_message
        assert "greater than 0" in error_message


# ==============================================================================
# UT-TC11..UT-TC12: Backward compatibility
# ==============================================================================


class TestTimeoutConfigBackwardCompatibility:
    """
    Backward compatibility: old configs without the ``total`` field should
    default to 600.0. The ``total`` field was added later and must not break
    existing YAML configs that omit it.
    """

    def test_ut_tc11_direct_construction_without_total(self):
        """
        Direct TimeoutConfig construction without the ``total`` keyword
        argument defaults total to 600.0.

        This simulates an old-style instantiation that predates the
        ``total`` field.
        """
        timeouts = TimeoutConfig(connect=5.0, read=30.0, write=10.0, pool=10.0)
        assert timeouts.total == 600.0
        assert timeouts.connect == 5.0
        assert timeouts.read == 30.0

    def test_ut_tc12_yaml_without_total_defaults_to_600(self):
        """
        Backward compatibility: a YAML config that specifies timeouts but
        omits the ``total`` field defaults ``total`` to 600.0 when loaded
        through ConfigLoader.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    timeouts:
      connect: 5.0
      read: 30.0
      write: 10.0
      pool: 10.0
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            provider = config.providers["test_provider"]
            assert provider.timeouts.connect == 5.0
            assert provider.timeouts.read == 30.0
            assert provider.timeouts.write == 10.0
            assert provider.timeouts.pool == 10.0
            # total was omitted — should default to 600.0
            assert provider.timeouts.total == 600.0


# ==============================================================================
# UT-TC13..UT-TC15: YAML loading
# ==============================================================================


class TestTimeoutConfigYamlLoading:
    """Test TimeoutConfig behaviour when loaded from YAML via ConfigLoader."""

    def test_ut_tc13_custom_total_from_yaml(self):
        """
        Scenario #6: Custom total timeout from YAML.

        WHEN the YAML config contains ``timeouts: { total: 300.0, read: 120.0 }``
        THEN ``provider_config.timeouts.total`` SHALL be ``300.0``.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    timeouts:
      total: 300.0
      read: 120.0
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            provider = config.providers["test_provider"]
            assert provider.timeouts.total == 300.0
            assert provider.timeouts.read == 120.0
            # Unspecified fields retain their defaults
            assert provider.timeouts.connect == 10.0
            assert provider.timeouts.write == 20.0
            assert provider.timeouts.pool == 15.0

    def test_ut_tc14_yaml_with_no_timeouts_section(self):
        """
        WHEN a YAML config omits the ``timeouts`` section entirely,
        THEN the provider's ``timeouts`` is a default ``TimeoutConfig()``
        with all defaults including ``total=600.0``.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            provider = config.providers["test_provider"]
            assert isinstance(provider.timeouts, TimeoutConfig)
            assert provider.timeouts.connect == 10.0
            assert provider.timeouts.read == 120.0
            assert provider.timeouts.write == 20.0
            assert provider.timeouts.pool == 15.0
            assert provider.timeouts.total == 600.0

    def test_ut_tc15_yaml_with_all_timeout_fields(self):
        """
        YAML config with all TimeoutConfig fields set to explicit values
        loads correctly and all values match.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    timeouts:
      connect: 3.0
      read: 45.0
      write: 7.0
      pool: 4.0
      total: 90.0
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            provider = config.providers["test_provider"]
            assert provider.timeouts.connect == 3.0
            assert provider.timeouts.read == 45.0
            assert provider.timeouts.write == 7.0
            assert provider.timeouts.pool == 4.0
            assert provider.timeouts.total == 90.0
