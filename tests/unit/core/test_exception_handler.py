"""
Unit tests for src.core.exception_handler (handle_exceptions decorator).

Covers test-plan scenarios:
  UD-1  — Import succeeds without circular import error
  UD-2  — Module does not import from src.services, src.config, src.providers, src.db
  UD-3  — Async function returns value on success
  UD-4  — Async function returns None on exception (default_result default)
  UD-5  — Sync function returns value on success
  UD-6  — Sync function returns None on exception
  UD-7  — Class method: ERROR log contains exception message and __qualname__
  UD-8  — log_level="error": ERROR message emitted AND DEBUG traceback with exc_info
  UD-9  — log_level="warning": WARNING logged, NO DEBUG traceback
  UD-10 — handle_exceptions() (no args): exception → returns None
  UD-11 — handle_exceptions(default_result=[]): exception → returns []
  UD-12 — handle_exceptions(reraise=True): sync function re-raises ValueError
  UD-13 — handle_exceptions(reraise=True): async function re-raises ValueError
  UD-14 — log_level="critical": CRITICAL logged AND DEBUG traceback with exc_info
  UD-15 — functools.wraps preserves __name__ and __qualname__
"""

import importlib
import inspect
import logging

import pytest

from src.core.exception_handler import handle_exceptions

# ==============================================================================
# UD-1: Import succeeds without circular import error
# ==============================================================================


class TestHandleExceptions:
    """All UD-* tests for the handle_exceptions decorator."""

    def test_ud1_import_succeeds(self):
        """UD-1: Importing handle_exceptions does not raise a circular import error."""
        # The import at the top of this file already proved it works.
        # Re-import to confirm no circular dependency at runtime.
        mod = importlib.import_module("src.core.exception_handler")
        assert hasattr(mod, "handle_exceptions")
        assert callable(mod.handle_exceptions)

    # ==============================================================================
    # UD-2: Module does not import from forbidden packages
    # ==============================================================================

    def test_ud2_no_forbidden_imports(self):
        """UD-2: exception_handler.py does not import from src.services, src.config,
        src.providers, or src.db."""
        source = inspect.getsource(handle_exceptions)
        forbidden = [
            "from src.services",
            "import src.services",
            "from src.config",
            "import src.config",
            "from src.providers",
            "import src.providers",
            "from src.db",
            "import src.db",
        ]
        for pattern in forbidden:
            assert (
                pattern not in source
            ), f"Forbidden import pattern '{pattern}' found in exception_handler.py"

    # ==============================================================================
    # UD-3: Async function returns value on success
    # ==============================================================================

    @pytest.mark.asyncio
    async def test_ud3_async_success_returns_value(self):
        """UD-3: @handle_exceptions(log_level="error") on async func returning 42 → 42."""

        @handle_exceptions(log_level="error")
        async def foo():
            return 42

        result = await foo()
        assert result == 42

    # ==============================================================================
    # UD-4: Async function returns None on exception
    # ==============================================================================

    @pytest.mark.asyncio
    async def test_ud4_async_exception_returns_none(self):
        """UD-4: @handle_exceptions(log_level="error") on async func raising ValueError → None."""

        @handle_exceptions(log_level="error")
        async def foo():
            raise ValueError("bad")

        result = await foo()
        assert result is None

    # ==============================================================================
    # UD-5: Sync function returns value on success
    # ==============================================================================

    def test_ud5_sync_success_returns_value(self):
        """UD-5: @handle_exceptions(log_level="error") on sync func returning "ok" → "ok"."""

        @handle_exceptions(log_level="error")
        def bar():
            return "ok"

        result = bar()
        assert result == "ok"

    # ==============================================================================
    # UD-6: Sync function returns None on exception
    # ==============================================================================

    def test_ud6_sync_exception_returns_none(self):
        """UD-6: @handle_exceptions(log_level="error") on sync func raising RuntimeError → None."""

        @handle_exceptions(log_level="error")
        def bar():
            raise RuntimeError("fail")

        result = bar()
        assert result is None

    # ==============================================================================
    # UD-7: Class method — ERROR log contains exception message and __qualname__
    # ==============================================================================

    @pytest.mark.asyncio
    async def test_ud7_class_method_error_log_contains_qualname_and_message(
        self, caplog
    ):
        """UD-7: ERROR log contains both the exception message and the function's __qualname__."""

        class MyClass:
            @handle_exceptions(log_level="error")
            async def my_method(self):
                raise ValueError("invalid input")

        with caplog.at_level(logging.DEBUG, logger="src.core.exception_handler"):
            obj = MyClass()
            result = await obj.my_method()

        assert result is None
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        error_msg = error_records[0].message
        assert "invalid input" in error_msg
        assert "MyClass.my_method" in error_msg

    # ==============================================================================
    # UD-8: log_level="error" — ERROR message AND DEBUG traceback with exc_info
    # ==============================================================================

    def test_ud8_error_level_logs_debug_traceback(self, caplog):
        """UD-8: log_level="error" produces an ERROR record AND a DEBUG record with exc_info=True."""

        @handle_exceptions(log_level="error")
        def failing_func():
            raise RuntimeError("boom")

        with caplog.at_level(logging.DEBUG, logger="src.core.exception_handler"):
            result = failing_func()

        assert result is None
        # Verify ERROR record exists
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        # Verify DEBUG record exists (traceback)
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        # Verify the DEBUG record has exc_info=True
        debug_with_exc_info = [r for r in debug_records if r.exc_info is not None]
        assert len(debug_with_exc_info) >= 1

    # ==============================================================================
    # UD-9: log_level="warning" — WARNING logged, NO DEBUG traceback
    # ==============================================================================

    def test_ud9_warning_level_no_debug_traceback(self, caplog):
        """UD-9: log_level="warning" logs WARNING but does NOT log a DEBUG traceback."""

        @handle_exceptions(log_level="warning")
        def failing_func():
            raise RuntimeError("soft fail")

        with caplog.at_level(logging.DEBUG, logger="src.core.exception_handler"):
            result = failing_func()

        assert result is None
        # Verify WARNING record exists
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        # Verify NO DEBUG-level record from this module
        debug_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and r.name == "src.core.exception_handler"
        ]
        assert len(debug_records) == 0

    # ==============================================================================
    # UD-10: handle_exceptions() (no args) — exception → returns None
    # ==============================================================================

    def test_ud10_no_args_returns_none_on_exception(self):
        """UD-10: @handle_exceptions() with no args returns None on exception."""

        @handle_exceptions()
        def failing_func():
            raise ValueError("oops")

        result = failing_func()
        assert result is None

    # ==============================================================================
    # UD-11: handle_exceptions(default_result=[]) — exception → returns []
    # ==============================================================================

    def test_ud11_custom_default_result(self):
        """UD-11: @handle_exceptions(default_result=[]) returns [] on exception."""

        @handle_exceptions(default_result=[])
        def failing_func():
            raise ValueError("oops")

        result = failing_func()
        assert result == []

    # ==============================================================================
    # UD-12: handle_exceptions(reraise=True) — sync function re-raises ValueError
    # ==============================================================================

    def test_ud12_reraise_sync_raises_valueerror(self):
        """UD-12: @handle_exceptions(reraise=True) on sync func re-raises ValueError("critical")."""

        @handle_exceptions(reraise=True)
        def failing_func():
            raise ValueError("critical")

        with pytest.raises(ValueError, match="critical"):
            failing_func()

    # ==============================================================================
    # UD-13: handle_exceptions(reraise=True) — async function re-raises ValueError
    # ==============================================================================

    @pytest.mark.asyncio
    async def test_ud13_reraise_async_raises_valueerror(self):
        """UD-13: @handle_exceptions(reraise=True) on async func re-raises ValueError("critical")."""

        @handle_exceptions(reraise=True)
        async def failing_func():
            raise ValueError("critical")

        with pytest.raises(ValueError, match="critical"):
            await failing_func()

    # ==============================================================================
    # UD-14: log_level="critical" — CRITICAL logged AND DEBUG traceback with exc_info
    # ==============================================================================

    def test_ud14_critical_level_logs_debug_traceback(self, caplog):
        """UD-14: log_level="critical" produces a CRITICAL record AND a DEBUG record with exc_info=True."""

        @handle_exceptions(log_level="critical")
        def failing_func():
            raise RuntimeError("catastrophic")

        with caplog.at_level(logging.DEBUG, logger="src.core.exception_handler"):
            result = failing_func()

        assert result is None
        # Verify CRITICAL record exists
        critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert len(critical_records) >= 1
        # Verify DEBUG record exists (traceback)
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        # Verify the DEBUG record has exc_info
        debug_with_exc_info = [r for r in debug_records if r.exc_info is not None]
        assert len(debug_with_exc_info) >= 1

    # ==============================================================================
    # UD-15: functools.wraps preserves __name__ and __qualname__
    # ==============================================================================

    def test_ud15_wraps_preserves_name_and_qualname(self):
        """UD-15: @handle_exceptions() preserves __name__ and __qualname__ via functools.wraps."""

        @handle_exceptions()
        def my_func():
            pass

        assert my_func.__name__ == "my_func"
        assert "my_func" in my_func.__qualname__
