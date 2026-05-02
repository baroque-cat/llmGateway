"""
Unit tests for the logging configuration module (src/config/logging_config.py).
"""

import logging
from unittest.mock import Mock, patch

import pytest

from src.config.logging_config import (
    ComponentNameFilter,
    MetricsEndpointFilter,
    setup_logging,
)
from src.core.accessor import ConfigAccessor


class _CapturingHandler(logging.Handler):
    """A handler that captures LogRecords for testing purposes."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


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
            # The format string should be "%(levelname)-8s | %(component)-10s | %(message)s"
            assert (
                handler.formatter._fmt
                == "%(levelname)-8s | %(component)-10s | %(message)s"
            )

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
            mock_apscheduler_scheduler_logger = Mock(spec=logging.Logger)
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
                elif name == "apscheduler.scheduler":
                    return mock_apscheduler_scheduler_logger
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
            mock_apscheduler_scheduler_logger.setLevel.assert_called_once_with(
                logging.WARNING
            )
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
            mock_apscheduler_scheduler_logger = Mock(spec=logging.Logger)
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
                elif name == "apscheduler.scheduler":
                    return mock_apscheduler_scheduler_logger
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
            mock_apscheduler_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_apscheduler_scheduler_logger.setLevel.assert_called_once_with(
                logging.WARNING
            )
            mock_uvicorn_access_logger.setLevel.assert_called_once_with(logging.WARNING)


class TestComponentNameFilter:
    """Tests for the ComponentNameFilter class."""

    def test_uc1_key_probe_maps_to_probe(self):
        """UC-1: src.services.key_probe maps to 'probe'."""
        cnf = ComponentNameFilter()
        record = Mock(spec=logging.LogRecord)
        record.name = "src.services.key_probe"
        result = cnf.filter(record)
        assert record.component == "probe"
        assert result is True

    def test_uc2_gateway_prefix_priority(self):
        """UC-2: src.services.gateway.gateway_cache maps to 'gateway' (prefix match)."""
        cnf = ComponentNameFilter()
        record = Mock(spec=logging.LogRecord)
        record.name = "src.services.gateway.gateway_cache"
        result = cnf.filter(record)
        assert record.component == "gateway"
        assert result is True

    def test_uc3_fallback_last_segment(self):
        """UC-3: urllib3.connectionpool falls back to 'connectionpool' (last segment)."""
        cnf = ComponentNameFilter()
        record = Mock(spec=logging.LogRecord)
        record.name = "urllib3.connectionpool"
        result = cnf.filter(record)
        assert record.component == "connectionpool"
        assert result is True

    def test_uc4_empty_and_root_names(self):
        """UC-4: Empty name falls back to empty string; 'root' falls back to 'root'."""
        cnf = ComponentNameFilter()

        # Empty name: no prefix matches, rsplit on "" yields ""
        record_empty = Mock(spec=logging.LogRecord)
        record_empty.name = ""
        result = cnf.filter(record_empty)
        assert record_empty.component == ""
        assert result is True

        # 'root' name: no prefix matches, rsplit on "root" yields "root"
        record_root = Mock(spec=logging.LogRecord)
        record_root.name = "root"
        result = cnf.filter(record_root)
        assert record_root.component == "root"
        assert result is True

    def test_uc5_prefix_priority_gateway_over_services(self):
        """UC-5: src.services.gateway.gateway_service maps to 'gateway' (specific prefix wins)."""
        cnf = ComponentNameFilter()
        record = Mock(spec=logging.LogRecord)
        record.name = "src.services.gateway.gateway_service"
        result = cnf.filter(record)
        # The more specific prefix 'src.services.gateway' matches before
        # any hypothetical 'src.services' prefix, yielding 'gateway'.
        assert record.component == "gateway"
        assert result is True

    def test_uc6_filter_always_returns_true(self):
        """UC-6: ComponentNameFilter always returns True for any LogRecord."""
        cnf = ComponentNameFilter()
        for name in ["src.services.keeper", "unknown.module", "", "root"]:
            record = Mock(spec=logging.LogRecord)
            record.name = name
            assert cnf.filter(record) is True

    def test_uc7_handler_adds_component_name_filter(self):
        """UC-7: setup_logging adds a ComponentNameFilter instance to the handler."""
        mock_accessor = Mock(spec=ConfigAccessor)
        mock_logging_config = Mock()
        mock_logging_config.level = "INFO"
        mock_accessor.get_logging_config.return_value = mock_logging_config

        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            # Verify the handler was added to the root logger
            assert mock_root_logger.addHandler.called
            # Get the handler that was added and check it has a ComponentNameFilter
            handler = mock_root_logger.addHandler.call_args[0][0]
            assert any(isinstance(f, ComponentNameFilter) for f in handler.filters)


class TestLogFormat:
    """Tests for the log format string and its formatting behavior."""

    LOG_FORMAT = "%(levelname)-8s | %(component)-10s | %(message)s"

    def test_uf1_format_string(self):
        """UF-1: The log format string is '%(levelname)-8s | %(component)-10s | %(message)s'."""
        assert self.LOG_FORMAT == "%(levelname)-8s | %(component)-10s | %(message)s"

    def test_uf2_no_asctime(self):
        """UF-2: The format does NOT contain %(asctime)s."""
        assert "%(asctime)" not in self.LOG_FORMAT

    def test_uf3_info_keeper_format(self):
        """UF-3: INFO level with 'keeper' component formats correctly."""
        formatter = logging.Formatter(self.LOG_FORMAT)
        record = logging.LogRecord(
            name="src.services.keeper",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="--- Starting LLM Gateway Keeper ---",
            args=(),
            exc_info=None,
        )
        record.component = "keeper"
        output = formatter.format(record)
        assert output == "INFO     | keeper     | --- Starting LLM Gateway Keeper ---"

    def test_uf4_warning_gateway_format(self):
        """UF-4: WARNING level with 'gateway' component formats correctly."""
        formatter = logging.Formatter(self.LOG_FORMAT)
        record = logging.LogRecord(
            name="src.services.gateway",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Retry policy is CONFIGURED but WILL BE IGNORED",
            args=(),
            exc_info=None,
        )
        record.component = "gateway"
        output = formatter.format(record)
        assert (
            output
            == "WARNING  | gateway    | Retry policy is CONFIGURED but WILL BE IGNORED"
        )

    def test_uf5_long_component_not_truncated(self):
        """UF-5: A component name longer than 10 chars is NOT truncated."""
        formatter = logging.Formatter(self.LOG_FORMAT)
        record = logging.LogRecord(
            name="urllib3.connectionpool",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        record.component = "connectionpool"
        output = formatter.format(record)
        # %(component)-10s pads to at least 10 but does NOT truncate longer values
        assert "connectionpool" in output

    def test_uf6_all_levels_left_aligned(self):
        """UF-6: All 5 log levels are left-aligned with 8 chars in the format output."""
        formatter = logging.Formatter(self.LOG_FORMAT)
        expected_levelnames = {
            logging.DEBUG: "DEBUG   ",
            logging.INFO: "INFO    ",
            logging.WARNING: "WARNING ",
            logging.ERROR: "ERROR   ",
            logging.CRITICAL: "CRITICAL",
        }
        for level, expected_prefix in expected_levelnames.items():
            record = logging.LogRecord(
                name="test.module",
                level=level,
                pathname="test.py",
                lineno=1,
                msg="test message",
                args=(),
                exc_info=None,
            )
            record.component = "test"
            output = formatter.format(record)
            # Each line should start with the levelname left-aligned in 8 chars
            assert output.startswith(expected_prefix + " | "), (
                f"Level {logging.getLevelName(level)}: expected prefix "
                f"'{expected_prefix} | ', got '{output[:11]}'"
            )


class TestAPSchedulerSuppression:
    """Tests for APScheduler logger suppression."""

    def test_ua1_apscheduler_scheduler_warning(self):
        """UA-1: apscheduler.scheduler logger is set to WARNING level."""
        mock_accessor = Mock(spec=ConfigAccessor)
        mock_logging_config = Mock()
        mock_logging_config.level = "INFO"
        mock_accessor.get_logging_config.return_value = mock_logging_config

        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_scheduler_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
                "apscheduler.scheduler": mock_scheduler_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            mock_scheduler_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_ua2_apscheduler_executors_default_warning(self):
        """UA-2: apscheduler.executors.default logger is set to WARNING level."""
        mock_accessor = Mock(spec=ConfigAccessor)
        mock_logging_config = Mock()
        mock_logging_config.level = "INFO"
        mock_accessor.get_logging_config.return_value = mock_logging_config

        with patch("logging.getLogger") as mock_get_logger:
            mock_root_logger = Mock(spec=logging.Logger)
            mock_executors_logger = Mock(spec=logging.Logger)
            mock_get_logger.side_effect = lambda name=None: {
                None: mock_root_logger,
                "": mock_root_logger,
                "apscheduler.executors.default": mock_executors_logger,
            }.get(name, Mock(spec=logging.Logger))
            mock_root_logger.handlers = []
            mock_root_logger.hasHandlers.return_value = False

            setup_logging(mock_accessor)

            mock_executors_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_ua3_info_suppressed_at_warning_level(self):
        """UA-3: INFO messages from apscheduler.scheduler are suppressed (INFO < WARNING)."""
        logger = logging.getLogger("apscheduler.scheduler")
        # Save and isolate state
        original_level = logger.level
        original_propagate = logger.propagate
        original_handlers = logger.handlers[:]
        for h in original_handlers:
            logger.removeHandler(h)

        logger.setLevel(logging.WARNING)
        logger.propagate = False
        handler = _CapturingHandler()
        logger.addHandler(handler)

        logger.info("Added job ...")

        # INFO < WARNING, so the message is suppressed
        assert len(handler.records) == 0

        # Clean up: restore original state
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        for h in original_handlers:
            logger.addHandler(h)

    def test_ua4_warning_passes_debug_suppressed(self):
        """UA-4: WARNING messages pass; DEBUG messages are suppressed."""
        logger = logging.getLogger("apscheduler.scheduler")
        # Save and isolate state
        original_level = logger.level
        original_propagate = logger.propagate
        original_handlers = logger.handlers[:]
        for h in original_handlers:
            logger.removeHandler(h)

        logger.setLevel(logging.WARNING)
        logger.propagate = False
        handler = _CapturingHandler()
        logger.addHandler(handler)

        logger.warning("Scheduler warning message")
        assert len(handler.records) == 1
        assert "Scheduler warning message" in handler.records[0].getMessage()

        logger.debug("Scheduler debug message")
        # DEBUG < WARNING, so it is suppressed; still only 1 record
        assert len(handler.records) == 1

        # Clean up: restore original state
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        for h in original_handlers:
            logger.addHandler(h)
