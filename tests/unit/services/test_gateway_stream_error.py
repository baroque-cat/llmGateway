"""
Unit tests for GatewayStreamError — domain exception (group G4).

Scenarios from test-plan.md:
  6.1  GatewayStreamError inherits Exception, has provider_name/model_name/error_reason attrs
  6.7  All async for sites are covered by try/except httpx.ReadError (source code inspection)
"""

import ast
import inspect

import pytest

from src.core.constants import ErrorReason
from src.services.gateway.gateway_service import GatewayStreamError

# ---------------------------------------------------------------------------
# 6.1  GatewayStreamError — domain exception
# ---------------------------------------------------------------------------


class TestGatewayStreamErrorInheritance:
    """Tests for inheritance and basic properties of GatewayStreamError."""

    def test_inherits_exception(self) -> None:
        """GatewayStreamError must inherit from Exception."""
        assert issubclass(GatewayStreamError, Exception)

    def test_is_not_base_exception_subclass_directly(self) -> None:
        """GatewayStreamError inherits Exception specifically, not BaseException directly."""
        # GatewayStreamError -> Exception -> BaseException
        assert GatewayStreamError.__bases__ == (Exception,)


class TestGatewayStreamErrorAttributes:
    """Tests for provider_name, model_name, error_reason attributes."""

    def test_default_error_reason_is_stream_disconnect(self) -> None:
        """Without explicit error_reason the default is STREAM_DISCONNECT."""
        exc = GatewayStreamError(
            "stream broken", provider_name="openai", model_name="gpt-4"
        )
        assert exc.error_reason == ErrorReason.STREAM_DISCONNECT

    def test_provider_name_attribute(self) -> None:
        """The provider_name attribute stores the given value."""
        exc = GatewayStreamError("msg", provider_name="my_provider", model_name="gpt-4")
        assert exc.provider_name == "my_provider"

    def test_model_name_attribute(self) -> None:
        """The model_name attribute stores the given value."""
        exc = GatewayStreamError("msg", provider_name="p", model_name="claude-3")
        assert exc.model_name == "claude-3"

    def test_explicit_error_reason_overrides_default(self) -> None:
        """If another error_reason is given, it replaces the default."""
        exc = GatewayStreamError(
            "msg",
            provider_name="p",
            model_name="m",
            error_reason=ErrorReason.NETWORK_ERROR,
        )
        assert exc.error_reason == ErrorReason.NETWORK_ERROR
        assert exc.error_reason != ErrorReason.STREAM_DISCONNECT

    def test_message_stored_in_exception(self) -> None:
        """The message is passed to Exception.__init__ and available via str()."""
        exc = GatewayStreamError(
            "Stream disconnected by upstream provider 'openai'",
            provider_name="openai",
            model_name="gpt-4",
        )
        assert str(exc) == "Stream disconnected by upstream provider 'openai'"

    def test_keyword_only_provider_and_model(self) -> None:
        """provider_name and model_name are keyword-only parameters (after *)."""
        sig = inspect.signature(GatewayStreamError.__init__)
        # After '*' params must be keyword-only
        params = sig.parameters
        # 'message' — positional, 'provider_name'/'model_name'/'error_reason' — keyword-only
        assert params["provider_name"].kind == inspect.Parameter.KEYWORD_ONLY
        assert params["model_name"].kind == inspect.Parameter.KEYWORD_ONLY
        assert params["error_reason"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_args_tuple_contains_message(self) -> None:
        """Exception.args must contain the given message."""
        exc = GatewayStreamError("hello", provider_name="p", model_name="m")
        assert exc.args == ("hello",)


class TestGatewayStreamErrorRaiseAndCatch:
    """Tests for raise/catch behavior."""

    def test_raise_and_catch_as_gateway_stream_error(self) -> None:
        """The exception can be caught by GatewayStreamError type."""
        with pytest.raises(GatewayStreamError) as exc_info:
            raise GatewayStreamError("stream error", provider_name="p", model_name="m")
        assert exc_info.value.provider_name == "p"
        assert exc_info.value.model_name == "m"

    def test_catch_as_exception(self) -> None:
        """The exception can be caught by the base Exception type."""
        with pytest.raises(Exception) as exc_info:
            raise GatewayStreamError("stream error", provider_name="p", model_name="m")
        assert isinstance(exc_info.value, GatewayStreamError)

    def test_raise_from_httpx_read_error(self) -> None:
        """GatewayStreamError can be raised from httpx.ReadError (exception chaining)."""
        import httpx

        original = httpx.ReadError("connection lost")
        with pytest.raises(GatewayStreamError) as exc_info:
            raise GatewayStreamError(
                "stream disconnected",
                provider_name="p",
                model_name="m",
            ) from original
        assert exc_info.value.__cause__ is original
        assert isinstance(exc_info.value.__cause__, httpx.ReadError)


# ---------------------------------------------------------------------------
# 6.7  All async for sites covered by try/except httpx.ReadError
# ---------------------------------------------------------------------------


class TestStreamReadErrorProtection:
    """
    Source code inspection of gateway_service.py:
    every async for / aiter_bytes() call must be inside
    a try/except httpx.ReadError block.
    """

    @pytest.fixture
    def gateway_source(self) -> str:
        """Get the source code of the gateway_service module."""
        import src.services.gateway.gateway_service as mod

        return inspect.getsource(mod)

    @pytest.fixture
    def gateway_ast_tree(self, gateway_source: str) -> ast.Module:
        """AST tree of the gateway_service source code."""
        return ast.parse(gateway_source)

    # --- Helper: find all async-for and aiter_bytes() call sites ---

    def _find_async_for_nodes(self, tree: ast.Module) -> list[ast.AsyncFor]:
        """Find all AsyncFor nodes in the AST."""
        nodes: list[ast.AsyncFor] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFor):
                nodes.append(node)
        return nodes

    def _find_aiter_bytes_calls(self, tree: ast.Module) -> list[ast.Call]:
        """Find all .aiter_bytes() calls in the AST."""
        calls: list[ast.Call] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # node.func may be an ast.Attribute (.aiter_bytes)
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "aiter_bytes"
                ):
                    calls.append(node)
        return calls

    def _is_inside_try_except_read_error(
        self, target_node: ast.AST, tree: ast.Module
    ) -> bool:
        """
        Check that target_node is inside a try block
        that has an except-handler for httpx.ReadError.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            # Check target_node is inside the try body
            for child in ast.walk(node):
                if child is target_node:
                    # Found! Now check the except handlers
                    for handler in node.handlers:
                        # handler.type may be ast.Attribute (httpx.ReadError)
                        # or ast.Name (ReadError), or None (bare except)
                        if self._handler_catches_read_error(handler):
                            return True
                    return False
        return False

    def _handler_catches_read_error(self, handler: ast.ExceptHandler) -> bool:
        """Check that an except handler catches httpx.ReadError."""
        if handler.type is None:
            # bare except — not considered protection against ReadError
            return False

        # Direct match: httpx.ReadError
        if isinstance(handler.type, ast.Attribute):
            if (
                isinstance(handler.type.value, ast.Name)
                and handler.type.value.id == "httpx"
                and handler.type.attr == "ReadError"
            ):
                return True

        # Name match: ReadError (if imported directly)
        if isinstance(handler.type, ast.Name) and handler.type.id == "ReadError":
            return True

        return False

    # --- The actual tests ---

    def test_all_async_for_covered_by_try_except_read_error(
        self, gateway_ast_tree: ast.Module
    ) -> None:
        """
        Every async for in gateway_service.py must be inside
        a try/except httpx.ReadError block.
        """
        async_for_nodes = self._find_async_for_nodes(gateway_ast_tree)

        # In the current implementation there are no direct async for loops
        # in gateway_service.py — streaming reading is done through
        # StreamMonitor.__anext__, which uses await self.stream_iterator.__anext__()
        # and handles httpx.ReadError.
        # Therefore async for nodes may be absent.

        unprotected: list[str] = []
        for node in async_for_nodes:
            if not self._is_inside_try_except_read_error(node, gateway_ast_tree):
                # Get the source line for diagnostics
                unprotected.append(
                    f"async for at line {node.lineno}: " f"{ast.unparse(node.iter)}"
                )

        assert unprotected == [], (
            "Unprotected async for nodes (no try/except httpx.ReadError):\n"
            + "\n".join(unprotected)
        )

    def test_aiter_bytes_call_in_stream_monitor_is_protected(
        self, gateway_ast_tree: ast.Module
    ) -> None:
        """
        The .aiter_bytes() call in StreamMonitor.__init__ saves the iterator,
        and the actual reading in __anext__ is protected by try/except httpx.ReadError.

        Verify that aiter_bytes() is called exactly once
        (in StreamMonitor.__init__), and that the __anext__ method contains
        except httpx.ReadError.
        """
        aiter_calls = self._find_aiter_bytes_calls(gateway_ast_tree)

        # aiter_bytes() is called once — in StreamMonitor.__init__
        assert len(aiter_calls) == 1, (
            f"Expected exactly 1 aiter_bytes() call (in StreamMonitor.__init__), "
            f"found {len(aiter_calls)} at lines: "
            f"{', '.join(str(c.lineno) for c in aiter_calls)}"
        )

        # Now verify that the __anext__ method of StreamMonitor
        # contains except httpx.ReadError
        stream_monitor_class = None
        for node in ast.walk(gateway_ast_tree):
            if isinstance(node, ast.ClassDef) and node.name == "StreamMonitor":
                stream_monitor_class = node
                break

        assert (
            stream_monitor_class is not None
        ), "StreamMonitor class not found in gateway_service.py"

        # Find the __anext__ method
        anext_method = None
        for item in stream_monitor_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == "__anext__":
                    anext_method = item
                    break

        assert (
            anext_method is not None
        ), "__anext__ method not found in StreamMonitor class"

        # Verify __anext__ contains a try with except httpx.ReadError
        has_read_error_handler = False
        for node in ast.walk(anext_method):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if self._handler_catches_read_error(handler):
                        has_read_error_handler = True
                        break

        assert has_read_error_handler, (
            "StreamMonitor.__anext__ does not have " "except httpx.ReadError handler"
        )

    def test_stream_monitor_anext_raises_gateway_stream_error_on_read_error(
        self, gateway_ast_tree: ast.Module
    ) -> None:
        """
        In __anext__ on httpx.ReadError there must be a raise GatewayStreamError(...).
        Verify via AST that the except httpx.ReadError block contains
        raise GatewayStreamError.
        """
        # Find StreamMonitor.__anext__
        stream_monitor_class = None
        for node in ast.walk(gateway_ast_tree):
            if isinstance(node, ast.ClassDef) and node.name == "StreamMonitor":
                stream_monitor_class = node
                break

        anext_method = None
        for item in stream_monitor_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == "__anext__":
                    anext_method = item
                    break

        # Find the except httpx.ReadError handler in __anext__
        read_error_handler = None
        for node in ast.walk(anext_method):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if self._handler_catches_read_error(handler):
                        read_error_handler = handler
                        break

        assert (
            read_error_handler is not None
        ), "No except httpx.ReadError handler found in __anext__"

        # Verify that handler.body contains raise GatewayStreamError
        has_gateway_stream_error_raise = False
        for node in ast.walk(read_error_handler):
            if isinstance(node, ast.Raise):
                # node.exc may be ast.Call(GatewayStreamError(...))
                # or ast.Name(GatewayStreamError)
                if isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name):
                        if node.exc.func.id == "GatewayStreamError":
                            has_gateway_stream_error_raise = True
                    elif isinstance(node.exc.func, ast.Attribute):
                        if node.exc.func.attr == "GatewayStreamError":
                            has_gateway_stream_error_raise = True
                elif isinstance(node.exc, ast.Name):
                    if node.exc.id == "GatewayStreamError":
                        has_gateway_stream_error_raise = True

        assert has_gateway_stream_error_raise, (
            "except httpx.ReadError handler in __anext__ does not "
            "raise GatewayStreamError"
        )
