#!/usr/bin/env python3

"""
Test suite for KeyExportConfig, KeyInventoryConfig, and their integration with ProviderConfig.

These tests verify that:
- KeyExportConfig defaults are correct (enabled=False, clean_raw_after_sync=True, snapshot_interval_hours=0)
- KeyInventoryConfig defaults are correct (enabled=False, interval_minutes=1440, statuses=[])
- Invalid status strings in KeyInventoryConfig raise ValidationError
- Valid status strings are accepted and coerced to Status enum members
- ProviderConfig always provides a KeyExportConfig with valid defaults
- key_export field is ordered after worker_health_policy in ProviderConfig
- Snapshot and inventory features can be independently enabled/disabled

Reference: openspec/changes/key-export-system/test-plan.md, Group 1
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import KeyExportConfig, KeyInventoryConfig, ProviderConfig
from src.core.constants import Status


class TestKeyExportConfigDefaults:
    """Tests for KeyExportConfig default values."""

    def test_key_export_config_defaults_disabled(self) -> None:
        """KeyExportConfig() has enabled=False by default."""
        config = KeyExportConfig()
        assert config.enabled is False

    def test_key_export_config_clean_raw_after_sync_default_true(self) -> None:
        """KeyExportConfig() has clean_raw_after_sync=True by default."""
        config = KeyExportConfig()
        assert config.clean_raw_after_sync is True

    def test_key_export_config_snapshot_interval_default_zero(self) -> None:
        """KeyExportConfig() has snapshot_interval_hours=0 by default."""
        config = KeyExportConfig()
        assert config.snapshot_interval_hours == 0

    def test_key_export_config_inventory_default(self) -> None:
        """KeyExportConfig() inventory is KeyInventoryConfig with enabled=False, interval_minutes=1440, statuses=[]."""
        config = KeyExportConfig()
        assert isinstance(config.inventory, KeyInventoryConfig)
        assert config.inventory.enabled is False
        assert config.inventory.interval_minutes == 1440
        assert config.inventory.statuses == []

    def test_key_export_config_explicit_values(self) -> None:
        """KeyExportConfig with all explicit values preserves them."""
        config = KeyExportConfig(
            enabled=True,
            clean_raw_after_sync=False,
            snapshot_interval_hours=12,
        )
        assert config.enabled is True
        assert config.clean_raw_after_sync is False
        assert config.snapshot_interval_hours == 12


class TestKeyInventoryConfig:
    """Tests for KeyInventoryConfig defaults, validation, and edge cases."""

    def test_key_inventory_config_defaults(self) -> None:
        """KeyInventoryConfig() with defaults: enabled=False, interval_minutes=1440, statuses=[]."""
        config = KeyInventoryConfig()
        assert config.enabled is False
        assert config.interval_minutes == 1440
        assert config.statuses == []

    def test_key_inventory_config_invalid_status_raises_validation_error(self) -> None:
        """KeyInventoryConfig(statuses=["valid", "no_quota", "garbage"]) raises ValidationError for "garbage"."""
        with pytest.raises(ValidationError) as exc_info:
            KeyInventoryConfig(statuses=["valid", "no_quota", "garbage"])

        error_message = str(exc_info.value)
        # The error should mention that "garbage" is not a valid Status value
        assert "garbage" in error_message

    def test_key_inventory_config_valid_statuses_accepted(self) -> None:
        """KeyInventoryConfig(statuses=["valid", "no_quota", "rate_limited"]) works and coerces to Status members."""
        config = KeyInventoryConfig(statuses=["valid", "no_quota", "rate_limited"])
        assert len(config.statuses) == 3
        assert config.statuses[0] == Status.VALID
        assert config.statuses[1] == Status.NO_QUOTA
        assert config.statuses[2] == Status.RATE_LIMITED

    def test_key_inventory_config_interval_minutes_positive(self) -> None:
        """KeyInventoryConfig(interval_minutes=30) is valid and preserves the value."""
        config = KeyInventoryConfig(interval_minutes=30)
        assert config.interval_minutes == 30

    def test_key_inventory_config_empty_statuses_valid(self) -> None:
        """KeyInventoryConfig(statuses=[]) is valid and results in an empty list."""
        config = KeyInventoryConfig(statuses=[])
        assert config.statuses == []


class TestProviderConfigKeyExportIntegration:
    """Tests for KeyExportConfig / KeyInventoryConfig integration with ProviderConfig."""

    def test_provider_config_key_export_always_present(self) -> None:
        """ProviderConfig(provider_type="gemini") without key_export has valid KeyExportConfig defaults."""
        provider = ProviderConfig(provider_type="gemini")
        assert isinstance(provider.key_export, KeyExportConfig)
        assert provider.key_export.enabled is False
        assert provider.key_export.clean_raw_after_sync is True
        assert provider.key_export.snapshot_interval_hours == 0
        assert isinstance(provider.key_export.inventory, KeyInventoryConfig)
        assert provider.key_export.inventory.enabled is False

    def test_provider_config_key_export_position_after_worker_health_policy(
        self,
    ) -> None:
        """key_export is ordered after worker_health_policy in ProviderConfig model fields."""
        field_names = list(ProviderConfig.model_fields.keys())
        worker_health_idx = field_names.index("worker_health_policy")
        key_export_idx = field_names.index("key_export")
        assert key_export_idx > worker_health_idx


class TestSnapshotAndInventoryIndependence:
    """Tests that snapshot and inventory features can be independently enabled/disabled."""

    def test_snapshot_and_inventory_independent_enabled_snapshot_only(self) -> None:
        """Snapshot enabled (interval=24), inventory disabled."""
        config = KeyExportConfig(
            enabled=True,
            snapshot_interval_hours=24,
            inventory=KeyInventoryConfig(enabled=False),
        )
        assert config.enabled is True
        assert config.snapshot_interval_hours == 24
        assert config.inventory.enabled is False

    def test_snapshot_and_inventory_independent_enabled_inventory_only(self) -> None:
        """Snapshot disabled (interval=0), inventory enabled with statuses=["valid"]."""
        config = KeyExportConfig(
            enabled=True,
            snapshot_interval_hours=0,
            inventory=KeyInventoryConfig(enabled=True, statuses=["valid"]),
        )
        assert config.enabled is True
        assert config.snapshot_interval_hours == 0
        assert config.inventory.enabled is True
        assert config.inventory.statuses == [Status.VALID]
