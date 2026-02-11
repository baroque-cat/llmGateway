"""
Integration test for the worker log format in KeyProbe.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.constants import ALL_MODELS_MARKER, ErrorReason
from src.core.models import CheckResult
from src.services.probes.key_probe import KeyProbe


class TestWorkerLogFormat:
    """Test the logging format emitted by the KeyProbe worker."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor."""
        mock = Mock()
        mock.get_worker_concurrency.return_value = 5
        return mock

    @pytest.fixture
    def mock_db_manager(self):
        """Provide a mock DatabaseManager."""
        db = Mock()
        db.keys = Mock()
        db.keys.update_status = AsyncMock()
        return db

    @pytest.fixture
    def mock_client_factory(self):
        """Provide a mock HttpClientFactory."""
        return Mock()

    @pytest.fixture
    def probe(self, mock_accessor, mock_db_manager, mock_client_factory):
        """Create a KeyProbe instance with mocked dependencies."""
        return KeyProbe(
            accessor=mock_accessor,
            db_manager=mock_db_manager,
            client_factory=mock_client_factory,
        )

    @pytest.mark.asyncio
    async def test_worker_log_format_shared_model(
        self, probe, mock_accessor, mock_db_manager
    ):
        """Verify log format when model is shared (ALL_MODELS_MARKER)."""
        # Mock provider existence
        mock_accessor.get_provider.return_value = Mock()
        # Mock health policy
        mock_accessor.get_health_policy.return_value = Mock(
            on_success_hr=24,
            stop_checking_after_days=30,
            quarantine_after_days=7,
            quarantine_recheck_interval_days=1,
            on_invalid_key_days=30,
            on_no_access_days=30,
            on_rate_limit_hr=1,
            on_no_quota_hr=1,
            on_overload_min=5,
            on_server_error_min=1,
            on_other_error_hr=6,
            amnesty_threshold_days=7,
        )
        # Simulate a successful check result
        result = CheckResult.success()
        resource = {
            "key_id": 42,
            "provider_name": "openai",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": None,
            "next_check_time": datetime.now(UTC) - timedelta(hours=1),
        }
        with patch("src.services.probes.key_probe.logger") as mock_logger:
            await probe._update_resource_status(resource, result)
            # Verify DB update was called
            mock_db_manager.keys.update_status.assert_called_once()
            # Verify log format
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            # Expected format: WORKER_CHECK | Key 42 | openai:shared | -> VALID (Next: ...)
            assert log_message.startswith(
                "WORKER_CHECK | Key 42 | openai:shared | -> VALID"
            )
            assert "(Next:" in log_message

    @pytest.mark.asyncio
    async def test_worker_log_format_specific_model(
        self, probe, mock_accessor, mock_db_manager
    ):
        """Verify log format for a specific model."""
        # Mock provider existence
        mock_accessor.get_provider.return_value = Mock()
        # Mock health policy
        mock_accessor.get_health_policy.return_value = Mock(
            on_success_hr=24,
            stop_checking_after_days=30,
            quarantine_after_days=7,
            quarantine_recheck_interval_days=1,
            on_invalid_key_days=30,
            on_no_access_days=30,
            on_rate_limit_hr=1,
            on_no_quota_hr=1,
            on_overload_min=5,
            on_server_error_min=1,
            on_other_error_hr=6,
            amnesty_threshold_days=7,
        )
        result = CheckResult.fail(ErrorReason.RATE_LIMITED)
        resource = {
            "key_id": 99,
            "provider_name": "gemini",
            "model_name": "gemini-2.0-flash",
            "failing_since": datetime.now(UTC) - timedelta(days=2),
            "next_check_time": datetime.now(UTC) - timedelta(hours=2),
        }
        with patch("src.services.probes.key_probe.logger") as mock_logger:
            await probe._update_resource_status(resource, result)
            mock_db_manager.keys.update_status.assert_called_once()
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            # Should contain model name as is
            assert "gemini:gemini-2.0-flash" in log_message
            assert "RATE_LIMITED" in log_message
            assert "(Next:" in log_message
