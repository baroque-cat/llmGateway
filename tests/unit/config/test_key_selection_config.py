"""Tests for KeySelectionConfig schema validation and GatewayPolicyConfig integration.

Covers spec capability ``sticky-key-selection`` / "Key selection mode is
configurable per provider":

  - Default mode is ``round_robin`` when ``key_selection`` is omitted.
  - Per-provider override to ``sticky`` is independent of other providers.
  - Invalid mode strings are rejected at config load with a clear message.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import GatewayPolicyConfig, KeySelectionConfig
from src.core.constants import KeySelectionMode
from tests._canonical import CanonicalConfig

# Canonical config for deriving default mode.
_cfg = CanonicalConfig.from_example_files()


class TestKeySelectionConfigDefaults:
    """Default mode when the section is omitted or left unset."""

    def test_default_mode_is_round_robin(self) -> None:
        """``KeySelectionConfig()`` defaults to ``ROUND_ROBIN``.

        The schema default is ``KeySelectionMode.ROUND_ROBIN``, matching the
        canonical YAML value in gemini-production.
        """
        config = KeySelectionConfig()
        assert config.mode is KeySelectionMode.ROUND_ROBIN
        assert config.mode == "round_robin"

    def test_default_is_via_gateway_policy_factory(self) -> None:
        """``GatewayPolicyConfig()`` creates a ``KeySelectionConfig`` with the default mode."""
        gp = GatewayPolicyConfig()
        assert gp.key_selection.mode is KeySelectionMode.ROUND_ROBIN
        assert gp.key_selection.mode == _cfg.key_selection_mode_default


class TestKeySelectionConfigPerProviderIndependence:
    """Per-provider overrides are independent — sticky on one, default on another."""

    def test_per_provider_override_to_sticky(self) -> None:
        """One ``GatewayPolicyConfig`` with sticky, another default — both independent."""
        sticky_gp = GatewayPolicyConfig(
            key_selection=KeySelectionConfig(mode=KeySelectionMode.STICKY),
        )
        default_gp = GatewayPolicyConfig()

        assert sticky_gp.key_selection.mode is KeySelectionMode.STICKY
        assert sticky_gp.key_selection.mode == "sticky"
        assert default_gp.key_selection.mode is KeySelectionMode.ROUND_ROBIN
        assert default_gp.key_selection.mode == "round_robin"


class TestKeySelectionConfigValidation:
    """Invalid mode strings are rejected at config load."""

    def test_invalid_mode_rejected_at_config_load(self) -> None:
        """Mode ``"random"`` (not in ``KeySelectionMode``) raises ``ValidationError``."""
        with pytest.raises(ValidationError) as exc_info:
            KeySelectionConfig(mode="random")  # type: ignore[arg-type]

        error_message = str(exc_info.value)
        assert "mode" in error_message or "random" in error_message

    def test_extra_fields_forbidden(self) -> None:
        """``KeySelectionConfig`` has ``extra='forbid'`` — unknown fields rejected."""
        with pytest.raises(ValidationError) as exc_info:
            KeySelectionConfig(mode="round_robin", unknown_field="value")  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        assert any(
            e.get("type") == "extra_forbidden" or "extra" in str(e.get("type", ""))
            for e in errors
        )
