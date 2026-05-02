"""
Security tests for the improve-logging-format change.

Validates that logging infrastructure does not leak sensitive data,
preserves exception integrity, and follows architectural constraints.

Tests:
  ST-1 — ComponentNameFilter does not expose sensitive data
  ST-2 — handle_exceptions does not log function arguments
  ST-3 — No circular imports from exception_handler
  ST-4 — reraise=True preserves exception type, message, and traceback
  ST-5 — Log format does not contain %(asctime)s
"""

import ast
import importlib.util
import logging
from unittest.mock import Mock

import pytest

from src.config.logging_config import ComponentNameFilter, setup_logging
from src.core.accessor import ConfigAccessor
from src.core.exception_handler import handle_exceptions


class TestLoggingSecurity:
    """Security tests for logging format and exception handling."""

    # ------------------------------------------------------------------
    # ST-1: ComponentNameFilter does not expose sensitive data
    # ------------------------------------------------------------------

    def test_st1_component_name_filter_no_sensitive_data(self) -> None:
        """ComponentNameFilter only operates on record.name (module path),
        never on log message content. It should not leak sensitive data
        from the message into the component attribute."""
        record = logging.LogRecord(
            name="src.services.keeper",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key: sk-abc123",
            args=None,
            exc_info=None,
        )
        original_msg = record.msg

        result = ComponentNameFilter().filter(record)

        # Filter always returns True (transparent — never drops records)
        assert result is True
        # Component is derived from the module path, not from message content
        assert record.component == "keeper"
        # Message content is untouched by the filter
        assert record.msg == original_msg
        # No sensitive data leaked into the component attribute
        assert "sk-abc123" not in record.component

    # ------------------------------------------------------------------
    # ST-2: handle_exceptions does not log function arguments
    # ------------------------------------------------------------------

    def test_st2_handle_exceptions_no_function_arguments_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """handle_exceptions logs only func.__qualname__ and str(exc),
        never the function arguments (which may contain secrets like
        API keys passed as parameters)."""

        @handle_exceptions(log_level="error")
        def my_func(secret_param: str = "sk-topsecret") -> None:
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            result = my_func()

        # Default result is None when reraise=False
        assert result is None

        # Error log should contain the exception message
        assert "boom" in caplog.text
        # Error log should contain the function qualname
        assert "my_func" in caplog.text

        # Error log should NOT contain function argument values
        assert "sk-topsecret" not in caplog.text
        # Error log should NOT contain parameter names
        assert "secret_param" not in caplog.text

    # ------------------------------------------------------------------
    # ST-3: No circular imports from exception_handler
    # ------------------------------------------------------------------

    def test_st3_no_circular_imports_from_exception_handler(self) -> None:
        """exception_handler.py imports only stdlib modules (asyncio,
        functools, logging, typing), preserving the architectural rule
        that core/ must not depend on services/, config/, providers/,
        or db/. No import from src. should exist in the module."""

        # Import should succeed without triggering circular dependencies
        from src.core.exception_handler import handle_exceptions as he

        assert he is not None

        # Verify by reading the source that no import from src. exists
        spec = importlib.util.find_spec("src.core.exception_handler")
        assert spec is not None
        assert spec.origin is not None

        with open(spec.origin) as f:
            tree = ast.parse(f.read())

        src_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("src."):
                    src_imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src."):
                        src_imports.append(alias.name)

        # No src. imports should exist in exception_handler.py
        assert (
            len(src_imports) == 0
        ), f"Found src. imports in exception_handler: {src_imports}"

    # ------------------------------------------------------------------
    # ST-4: reraise=True preserves exception type, message, and traceback
    # ------------------------------------------------------------------

    def test_st4_reraise_preserves_exception_type_message_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When reraise=True, the original exception type, message, and
        traceback are preserved — the decorator does not mask or wrap
        them in a different exception type."""

        @handle_exceptions(reraise=True)
        def will_raise() -> None:
            raise ValueError("specific error")

        with (
            pytest.raises(ValueError, match="specific error") as exc_info,
            caplog.at_level(logging.ERROR),
        ):
            will_raise()

        exc = exc_info.value

        # Exception type preserved (not wrapped or changed)
        assert isinstance(exc, ValueError)
        # Exception message preserved exactly
        assert str(exc) == "specific error"
        # Traceback is not None (not stripped by decorator)
        assert exc.__traceback__ is not None

        # Traceback contains the original function name
        tb_frames: list[str] = []
        tb = exc.__traceback__
        while tb is not None:
            tb_frames.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert (
            "will_raise" in tb_frames
        ), f"Traceback should contain 'will_raise', got: {tb_frames}"

    # ------------------------------------------------------------------
    # ST-5: Log format does not contain %(asctime)s
    # ------------------------------------------------------------------

    def test_st5_log_format_no_asctime(self) -> None:
        """The log format string must not contain %(asctime)s — timestamps
        are provided by the container runtime (docker/podman -t), not
        by the application's logging formatter."""

        mock_accessor = Mock(spec=ConfigAccessor)
        mock_logging_config = Mock()
        mock_logging_config.level = "INFO"
        mock_accessor.get_logging_config.return_value = mock_logging_config

        # Save root logger state for cleanup
        root = logging.getLogger()
        original_handlers = root.handlers.copy()
        original_level = root.level
        original_filters = root.filters.copy()

        try:
            setup_logging(mock_accessor)

            # Inspect the root logger's handler's formatter
            assert len(root.handlers) > 0
            handler = root.handlers[0]
            formatter = handler.formatter
            assert formatter is not None

            fmt = formatter._fmt
            assert "asctime" not in fmt.lower(), f"Log format contains asctime: {fmt}"
        finally:
            # Restore root logger state to avoid polluting other tests
            root.handlers.clear()
            for h in original_handlers:
                root.addHandler(h)
            root.setLevel(original_level)
            root.filters = list(original_filters)
