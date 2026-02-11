"""
Unit tests for the logging configuration module (src/config/logging_config.py).
"""

import logging
from unittest.mock import Mock, patch

import pytest

from src.config.logging_config import MetricsEndpointFilter, setup_logging
from src.core.accessor import ConfigAccessor


class TestMetricsEndpointFilter:
    """Tests for the MetricsEndpointFilter class."""

    def test_filter_metrics_endpoint(self):
        """Test that the filter drops log records containing '/metrics'."""
        filter = MetricsEndpointFilter()
        # Create a mock log record
        record = Mock(spec=logging.LogRecord)
        record.getMessage.return_value = "GET /metrics 200"
        assert filter.filter(record) is False

    def test_filter_non_metrics_endpoint(self):
        """Test that the filter passes log records not containing '/metrics'."""
        filter = MetricsEndpointFilter()
        record = Mock(spec=logging.LogRecord)
        record.getMessage.return_value = "GET /health 200"
        assert filter.filter(record) is True

    def test_filter_case_insensitive(self):
        """Test that the filter is case-sensitive (should not match)."""
        filter = MetricsEndpointFilter()
        record = Mock(spec=logging.LogRecord)
        record.getMessage.return_value = "GET /METRICS 200"
        # The filter looks for literal '/metrics' (lowercase) in the message
        # Since the message contains '/METRICS', it should pass
        assert filter.filter(record) is True


class TestLoggingConfiguration:
    """Tests for the setup_logging function."""

    @pytest.fixture
    def mock_accessor(self):
        """Provide a mock ConfigAccessor."""
        mock = Mock(spec=ConfigAccessor)
        # Mock logging config with level field
        mock_logging_config = Mock()
        mock_logging_config.level = "INFO"
        mock.get_logging_config.return_value = mock_logging_config
        return mock

    def test_logging_format(self, mock_accessor):
        """Verify that the logging format is set correctly."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_get_logger.return_value = mock_root_logger
            mock_root_logger.handlers = []  # Simulate no existing handlers

            # Call the function under test
            setup_logging(mock_accessor)

            # Verify that the root logger's handler uses the correct format
            assert mock_root_logger.addHandler.called
            handler = mock_root_logger.addHandler.call_args[0][0]
            # The handler should have a formatter with the expected format string
            assert handler.formatter is not None
            # The format string should be "%(name)s: %(message)s"
            assert handler.formatter._fmt == "%(name)s: %(message)s"

    def test_httpx_silence(self, mock_accessor):
        """Verify that httpx logger level is set to WARNING."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_httpx_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
                "httpx": mock_httpx_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            # Verify that httpx logger's level is set to WARNING
            mock_httpx_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_metrics_filter_applied(self, mock_accessor):
        """Verify that the MetricsEndpointFilter is added to uvicorn.access logger."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_uvicorn_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
                "uvicorn.access": mock_uvicorn_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            # Verify that the filter is added
            mock_uvicorn_logger.addFilter.assert_called_once()
            filter = mock_uvicorn_logger.addFilter.call_args[0][0]
            assert isinstance(filter, MetricsEndpointFilter)

    def test_logging_level_set(self, mock_accessor):
        """Verify that the root logger level is set according to config."""
        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as MockStreamHandler,
        ):
            # Create separate mocks for different loggers
            mock_root_logger = Mock(spec=logging.Logger)
            mock_httpx_logger = Mock(spec=logging.Logger)
            mock_apscheduler_logger = Mock(spec=logging.Logger)
            mock_urllib3_logger = Mock(spec=logging.Logger)
            mock_uvicorn_access_logger = Mock(spec=logging.Logger)
            mock_module_logger = Mock(spec=logging.Logger)

            # Map logger names to mocks
            def get_logger_side_effect(name=None):
                if name is None or name == "":
                    return mock_root_logger
                elif name == "httpx":
                    return mock_httpx_logger
                elif name == "apscheduler.executors.default":
                    return mock_apscheduler_logger
                elif name == "urllib3.connectionpool":
                    return mock_urllib3_logger
                elif name == "uvicorn.access":
                    return mock_uvicorn_access_logger
                elif name == "src.config.logging_config":
                    return mock_module_logger
                else:
                    return Mock(spec=logging.Logger)

            mock_get_logger.side_effect = get_logger_side_effect
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False
            # Mock handler
            mock_handler = Mock()
            MockStreamHandler.return_value = mock_handler

            # Test with INFO level (default)
            setup_logging(mock_accessor)
            # Root logger level should be INFO
            mock_root_logger.setLevel.assert_called_once_with(logging.INFO)
            # Handler level should also be INFO
            mock_handler.setLevel.assert_called_once_with(logging.INFO)
            # Also check that other loggers have appropriate levels
            mock_httpx_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_apscheduler_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_urllib3_logger.setLevel.assert_called_once_with(logging.INFO)
            mock_uvicorn_access_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_uvicorn_access_level_warning(self, mock_accessor):
        """Verify that uvicorn.access logger level is set to WARNING."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_uvicorn_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
                "uvicorn.access": mock_uvicorn_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            # Verify that uvicorn.access logger's level is set to WARNING
            mock_uvicorn_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_logging_level_debug(self):
        """Verify that the root logger level can be set to DEBUG."""
        # Create a fresh mock accessor with DEBUG level
        mock_accessor = Mock(spec=ConfigAccessor)
        mock_logging_config = Mock()
        mock_logging_config.level = "DEBUG"
        mock_accessor.get_logging_config.return_value = mock_logging_config

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as MockStreamHandler,
        ):
            mock_root_logger = Mock(spec=logging.Logger)
            mock_httpx_logger = Mock(spec=logging.Logger)
            mock_apscheduler_logger = Mock(spec=logging.Logger)
            mock_urllib3_logger = Mock(spec=logging.Logger)
            mock_uvicorn_access_logger = Mock(spec=logging.Logger)
            mock_module_logger = Mock(spec=logging.Logger)

            def get_logger_side_effect(name=None):
                if name is None or name == "":
                    return mock_root_logger
                elif name == "httpx":
                    return mock_httpx_logger
                elif name == "apscheduler.executors.default":
                    return mock_apscheduler_logger
                elif name == "urllib3.connectionpool":
                    return mock_urllib3_logger
                elif name == "uvicorn.access":
                    return mock_uvicorn_access_logger
                elif name == "src.config.logging_config":
                    return mock_module_logger
                else:
                    return Mock(spec=logging.Logger)

            mock_get_logger.side_effect = get_logger_side_effect
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False
            mock_handler = Mock()
            MockStreamHandler.return_value = mock_handler

            setup_logging(mock_accessor)
            # Root logger level should be DEBUG
            mock_root_logger.setLevel.assert_called_once_with(logging.DEBUG)
            # Handler level should also be DEBUG
            mock_handler.setLevel.assert_called_once_with(logging.DEBUG)
            # Other loggers remain unchanged
            mock_httpx_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_uvicorn_access_logger.setLevel.assert_called_once_with(logging.WARNING)
