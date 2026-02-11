#!/usr/bin/env python3
"""
Unit tests for logging verbosity after refactoring.
Verifies that logging levels are appropriate (DEBUG vs INFO) and string formatting.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.constants import ALL_MODELS_MARKER, ErrorReason
from src.core.models import CheckResult
from src.services.gateway_cache import GatewayCache
from src.services.probes.key_probe import KeyProbe


class TestGatewayCacheLoggingVerbosity:
    """Tests for GatewayCache logging levels."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor."""
        return Mock()

    @pytest.fixture
    def mock_db_manager(self):
        """Provide a mock DatabaseManager."""
        return Mock()

    @pytest.fixture
    def cache(self, mock_accessor, mock_db_manager):
        """Create a GatewayCache instance with mocked dependencies."""
        return GatewayCache(mock_accessor, mock_db_manager)

    @pytest.mark.asyncio
    async def test_refresh_key_pool_logs_at_debug(self, cache, mock_db_manager):
        """
        Test 1: Verify that GatewayCache.refresh_key_pool logs its message at DEBUG level, not INFO.
        """
        mock_db_manager.keys.get_all_valid_keys_for_caching = AsyncMock(
            return_value=[
                {
                    "key_id": 1,
                    "provider_name": "openai",
                    "model_name": "gpt-4",
                    "key_value": "sk-xxx",
                }
            ]
        )
        with patch("src.services.gateway_cache.logger") as mock_logger:
            await cache.refresh_key_pool()
            # Both start and success messages should be at DEBUG level
            assert mock_logger.debug.call_count >= 2
            debug_messages = [call[0][0] for call in mock_logger.debug.call_args_list]
            # Check for expected debug messages
            start_found = any(
                "Refreshing key pool cache from database" in msg
                for msg in debug_messages
            )
            success_found = any(
                "Key pool cache refreshed successfully" in msg for msg in debug_messages
            )
            assert start_found, "Start message not logged at DEBUG"
            assert success_found, "Success message not logged at DEBUG"
            # No INFO logs should be emitted for refresh operations
            mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_shared_key_removal_logs_debug_with_shared(
        self, cache, mock_accessor
    ):
        """
        Test 2: Verify that when a shared key is removed from the cache,
        the log message (now at DEBUG) contains the string ':shared' and NOT ':__ALL_MODELS__'.
        """
        mock_provider_config = Mock()
        mock_provider_config.shared_key_status = True
        mock_accessor.get_provider.return_value = mock_provider_config
        # Pre-populate a key in the pool with __ALL_MODELS__ marker
        cache._key_pool[f"openai:{ALL_MODELS_MARKER}"] = [(1, "sk-xxx")]
        with patch("src.services.gateway_cache.logger") as mock_logger:
            await cache.remove_key_from_pool("openai", "gpt-4", 1)
            # Should log DEBUG about removing shared key
            mock_logger.info.assert_not_called()
            # Find the call about shared key in debug logs
            shared_call = None
            for call in mock_logger.debug.call_args_list:
                if "shared key_id" in call[0][0]:
                    shared_call = call
                    break
            assert shared_call is not None
            message = shared_call[0][0]
            assert "Removing shared key_id 1 from virtual pool" in message
            assert "openai:shared" in message
            assert ":__ALL_MODELS__" not in message


class TestKeyProbeLoggingVerbosity:
    """Tests for KeyProbe logging levels."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mocked dependencies for KeyProbe."""
        mock_accessor = Mock()
        mock_accessor.get_worker_concurrency.return_value = 10
        mock_db = Mock()
        mock_db.keys.update_status = AsyncMock()
        mock_client_factory = Mock()
        mock_client_factory.get_client_for_provider = AsyncMock()
        return mock_accessor, mock_db, mock_client_factory

    @pytest.mark.asyncio
    async def test_fatal_error_logs_only_one_info_line(self, mock_dependencies):
        """
        Test 3: Verify that the KeyProbe service, when encountering a fatal error,
        only produces one INFO log line (the WORKER_CHECK summary) and the detailed
        failure reason is logged at DEBUG.
        """
        mock_accessor, mock_db, mock_client_factory = mock_dependencies
        # Setup provider config
        mock_provider_config = Mock()
        mock_accessor.get_provider.return_value = mock_provider_config
        mock_accessor.get_provider_or_raise.return_value = mock_provider_config
        # Mock health policy
        mock_health_policy = Mock()
        mock_health_policy.amnesty_threshold_days = 2.0
        mock_health_policy.quarantine_after_days = 30
        mock_health_policy.stop_checking_after_days = 90
        mock_health_policy.on_invalid_key_days = 10
        mock_health_policy.on_no_access_days = 10
        mock_health_policy.on_rate_limit_hr = 4
        mock_health_policy.on_no_quota_hr = 4
        mock_health_policy.on_overload_min = 60
        mock_health_policy.on_server_error_min = 30
        mock_health_policy.on_other_error_hr = 1
        mock_health_policy.on_success_hr = 24
        mock_health_policy.quarantine_recheck_interval_days = 10
        mock_health_policy.verification_attempts = 3
        mock_health_policy.verification_delay_sec = 1
        mock_accessor.get_health_policy.return_value = mock_health_policy
        # Mock the client factory to return a mock client
        mock_client = AsyncMock()
        mock_client_factory.get_client_for_provider.return_value = mock_client
        # Mock the provider instance to return a fatal error
        with patch("src.services.probes.key_probe.get_provider") as mock_get_provider:
            mock_provider_instance = Mock()
            mock_provider_instance.check = AsyncMock(
                return_value=CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")
            )
            mock_get_provider.return_value = mock_provider_instance
            probe = KeyProbe(mock_accessor, mock_db, mock_client_factory)
            # Prepare a resource (key) to check with proper datetime objects
            from datetime import UTC, datetime, timedelta

            now = datetime.now(UTC)
            resource = {
                "key_id": 1,
                "provider_name": "openai",
                "model_name": "gpt-4",
                "key_value": "sk-xxx",
                "failing_since": None,
                "next_check_time": now - timedelta(minutes=5),  # slightly overdue
            }
            with patch("src.services.probes.key_probe.logger") as mock_logger:
                result = await probe._check_resource(resource)
                # Verify that the fatal error was logged at DEBUG level
                fatal_debug_found = any(
                    "fatal error" in call[0][0].lower()
                    for call in mock_logger.debug.call_args_list
                )
                assert fatal_debug_found, "Fatal error not logged at DEBUG"
                # Verify that no INFO logs were produced during the check phase
                mock_logger.info.assert_not_called()
                # Now simulate the update phase (which logs WORKER_CHECK at INFO)
                # We need to call _update_resource_status with the same result
                await probe._update_resource_status(resource, result)
                # Exactly one INFO log should be emitted (the WORKER_CHECK summary)
                assert mock_logger.info.call_count == 1
                info_message = mock_logger.info.call_args[0][0]
                assert "WORKER_CHECK" in info_message
                assert "INVALID_KEY" in info_message
