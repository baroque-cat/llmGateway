"""
Integration tests for the improved logging format (OpenSpec: improve-logging-format).

Tests the full integration of ComponentNameFilter, the new log format,
apscheduler suppression, handle_exceptions in async context,
MetricsEndpointFilter, and compatibility with existing e2e tests.

Test IDs: IE-1 through IE-7 (IE-6 is a separate e2e test run).
"""

import asyncio
import io
import logging
from unittest.mock import Mock

import pytest

from src.config.logging_config import setup_logging
from src.core.accessor import ConfigAccessor
from src.core.exception_handler import handle_exceptions

# Format string used by setup_logging
LOG_FORMAT = "%(levelname)-8s | %(component)-10s | %(message)s"


class TestLoggingFormatIntegration:
    """Integration tests verifying the logging format works end-to-end."""

    @pytest.fixture
    def logging_env(self):
        """Set up logging with a mock accessor (INFO level) and clean up after."""
        root = logging.getLogger()

        # Save root logger state before any modifications
        saved_root_handlers = root.handlers[:]
        saved_root_filters = root.filters[:]
        saved_root_level = root.level

        # Save specific logger states that setup_logging modifies
        specific_names = [
            "uvicorn.access",
            "uvicorn.error",
            "apscheduler.scheduler",
            "apscheduler.executors.default",
            "urllib3.connectionpool",
            "httpx",
        ]
        saved_specific = {}
        for name in specific_names:
            lg = logging.getLogger(name)
            saved_specific[name] = {
                "handlers": lg.handlers[:],
                "filters": lg.filters[:],
                "level": lg.level,
                "propagate": lg.propagate,
            }

        # Create mock accessor with INFO level
        mock = Mock(spec=ConfigAccessor)
        mock_cfg = Mock()
        mock_cfg.level = "INFO"
        mock.get_logging_config.return_value = mock_cfg

        setup_logging(mock)

        yield mock

        # Restore root logger — clear first, then re-add saved items
        root.handlers.clear()
        root.filters.clear()
        root.setLevel(saved_root_level)
        for h in saved_root_handlers:
            root.addHandler(h)
        for f in saved_root_filters:
            root.addFilter(f)

        # Restore specific loggers
        for name, state in saved_specific.items():
            lg = logging.getLogger(name)
            lg.handlers.clear()
            lg.filters.clear()
            lg.setLevel(state["level"])
            lg.propagate = state["propagate"]
            for h in state["handlers"]:
                lg.addHandler(h)
            for f in state["filters"]:
                lg.addFilter(f)

    def _capture_via_root(
        self, logger_name: str, level: int, message: str, fmt: str = LOG_FORMAT
    ) -> str:
        """Emit a log message and capture formatted output via a StringIO handler on the root logger."""
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt))
        handler.setLevel(logging.DEBUG)  # Let all levels through the handler
        root.addHandler(handler)

        logger = logging.getLogger(logger_name)
        logger.log(level, message)

        output = stream.getvalue()
        root.removeHandler(handler)
        return output

    # ------------------------------------------------------------------
    # IE-1: Full format integration — keeper component
    # ------------------------------------------------------------------

    def test_ie1_keeper_format(self, logging_env):
        """IE-1: 'src.services.keeper' INFO → 'INFO     | keeper     | Test message'."""
        output = self._capture_via_root(
            "src.services.keeper", logging.INFO, "Test message"
        )
        # %(levelname)-8s  → "INFO    "  (8 chars, left-aligned) + " | " separator → 5 spaces before pipe
        # %(component)-10s → "keeper    " (10 chars, left-aligned) + " | " separator → 5 spaces before pipe
        expected = "INFO     | keeper     | Test message\n"
        assert output == expected, f"Expected:\n{expected!r}\nGot:\n{output!r}"

    # ------------------------------------------------------------------
    # IE-2: ComponentNameFilter + Formatter — gateway component
    # ------------------------------------------------------------------

    def test_ie2_gateway_format(self, logging_env):
        """IE-2: 'src.services.gateway.gateway_cache' WARNING → 'WARNING  | gateway    | Cache miss'."""
        output = self._capture_via_root(
            "src.services.gateway.gateway_cache", logging.WARNING, "Cache miss"
        )
        # %(levelname)-8s  → "WARNING  "  (8 chars, left-aligned) + " | " separator → 2 spaces before pipe
        # %(component)-10s → "gateway   "  (10 chars, left-aligned) + " | " separator → 4 spaces before pipe
        expected = "WARNING  | gateway    | Cache miss\n"
        assert output == expected, f"Expected:\n{expected!r}\nGot:\n{output!r}"

    # ------------------------------------------------------------------
    # IE-3: apscheduler.scheduler INFO suppressed
    # ------------------------------------------------------------------

    def test_ie3_apscheduler_info_suppressed(self, logging_env):
        """IE-3: apscheduler.scheduler INFO is suppressed (logger set to WARNING)."""
        output = self._capture_via_root(
            "apscheduler.scheduler", logging.INFO, "Added job ..."
        )
        assert (
            output == ""
        ), f"Expected empty output (INFO suppressed), got:\n{output!r}"

    # ------------------------------------------------------------------
    # IE-4: apscheduler.scheduler with DEBUG root — WARNING passes, INFO/DEBUG suppressed
    # ------------------------------------------------------------------

    def test_ie4_apscheduler_debug_root(self):
        """IE-4: With DEBUG root, apscheduler.scheduler WARNING passes; INFO/DEBUG suppressed."""
        root = logging.getLogger()

        # Save full state before this test's own setup_logging call
        saved_root_handlers = root.handlers[:]
        saved_root_filters = root.filters[:]
        saved_root_level = root.level

        specific_names = [
            "uvicorn.access",
            "uvicorn.error",
            "apscheduler.scheduler",
            "apscheduler.executors.default",
            "urllib3.connectionpool",
            "httpx",
        ]
        saved_specific = {}
        for name in specific_names:
            lg = logging.getLogger(name)
            saved_specific[name] = {
                "handlers": lg.handlers[:],
                "filters": lg.filters[:],
                "level": lg.level,
                "propagate": lg.propagate,
            }

        # Clean up before re-calling setup_logging
        root.handlers.clear()
        root.filters.clear()

        # Create mock accessor with DEBUG level
        mock = Mock(spec=ConfigAccessor)
        mock_cfg = Mock()
        mock_cfg.level = "DEBUG"
        mock.get_logging_config.return_value = mock_cfg

        setup_logging(mock)

        # Use a simple format to avoid %(component) issues — we only care about
        # presence/absence of messages here, not the exact format.
        simple_fmt = "%(levelname)-8s | %(message)s"

        # WARNING — should appear (WARNING >= apscheduler.scheduler's WARNING level)
        out_warn = self._capture_via_root(
            "apscheduler.scheduler", logging.WARNING, "Some warning", fmt=simple_fmt
        )
        assert "Some warning" in out_warn, f"WARNING should appear, got:\n{out_warn!r}"

        # INFO — should be suppressed (INFO < WARNING on apscheduler.scheduler)
        out_info = self._capture_via_root(
            "apscheduler.scheduler", logging.INFO, "Added job", fmt=simple_fmt
        )
        assert out_info == "", f"INFO should be suppressed, got:\n{out_info!r}"

        # DEBUG — should be suppressed (DEBUG < WARNING on apscheduler.scheduler)
        out_debug = self._capture_via_root(
            "apscheduler.scheduler", logging.DEBUG, "debug msg", fmt=simple_fmt
        )
        assert out_debug == "", f"DEBUG should be suppressed, got:\n{out_debug!r}"

        # Restore state
        root.handlers.clear()
        root.filters.clear()
        root.setLevel(saved_root_level)
        for h in saved_root_handlers:
            root.addHandler(h)
        for f in saved_root_filters:
            root.addFilter(f)
        for name, state in saved_specific.items():
            lg = logging.getLogger(name)
            lg.handlers.clear()
            lg.filters.clear()
            lg.setLevel(state["level"])
            lg.propagate = state["propagate"]
            for h in state["handlers"]:
                lg.addHandler(h)
            for f in state["filters"]:
                lg.addFilter(f)

    # ------------------------------------------------------------------
    # IE-5: handle_exceptions in real async context
    # ------------------------------------------------------------------

    def test_ie5_handle_exceptions_async(self, logging_env, caplog):
        """IE-5: @handle_exceptions(log_level="error") async → returns None, ERROR logged."""

        @handle_exceptions(log_level="error")
        async def failing_async():
            raise RuntimeError("async failure")

        with caplog.at_level(logging.ERROR):
            result = asyncio.run(failing_async())

        assert result is None, f"Expected None, got {result!r}"

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1, "Expected at least one ERROR record"
        assert (
            "async failure" in error_records[0].getMessage()
        ), f"Expected 'async failure' in error message, got: {error_records[0].getMessage()}"

    # ------------------------------------------------------------------
    # IE-7: MetricsEndpointFilter continues to work
    # ------------------------------------------------------------------

    def test_ie7_metrics_endpoint_filter(self, logging_env):
        """IE-7: MetricsEndpointFilter filters /metrics but not /health on uvicorn.access."""
        uvicorn_access = logging.getLogger("uvicorn.access")
        # Temporarily lower the level so INFO messages reach handlers
        original_level = uvicorn_access.level
        uvicorn_access.setLevel(logging.DEBUG)

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)
        uvicorn_access.addHandler(handler)

        # /metrics — should be filtered by MetricsEndpointFilter
        uvicorn_access.info("GET /metrics 200")
        out_metrics = stream.getvalue()
        assert out_metrics == "", f"/metrics should be filtered, got:\n{out_metrics!r}"

        # /health — should NOT be filtered
        uvicorn_access.info("GET /health 200")
        out_health = stream.getvalue()
        assert (
            "GET /health 200" in out_health
        ), f"/health should appear, got:\n{out_health!r}"

        # Cleanup: remove our handler and restore level
        uvicorn_access.removeHandler(handler)
        uvicorn_access.setLevel(original_level)
