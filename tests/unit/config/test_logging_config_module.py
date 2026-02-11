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
        return Mock(spec=ConfigAccessor)

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
