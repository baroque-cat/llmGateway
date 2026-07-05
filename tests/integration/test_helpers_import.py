"""Tests for the integration test helpers module.

Verifies that the helpers module provides importable utilities with
preserved APIs, following the spec in the integration-test-helpers spec.

Coverage rows: S8, S9, S11, S12, S13.
"""

import ast
import inspect
from pathlib import Path

from src.core.constants import DebugMode, StreamingMode
from tests.integration._helpers import (
    create_mock_provider_config,
    make_mock_request,
)


def test_make_mock_request_importable_statically() -> None:
    """S8: Explicit import resolves statically.

    ``from tests.integration._helpers import make_mock_request`` must
    resolve at runtime under pytest, and ``ruff check`` must report
    zero F821 (undefined-name) errors.
    """
    assert make_mock_request is not None
    assert callable(make_mock_request)


def test_helpers_use_absolute_import_syntax() -> None:
    """S9: Import style follows project conventions.

    The import statement must use absolute import syntax
    (``from tests.integration._helpers import ...``), not relative
    (``from ._helpers import ...``).
    """
    source = Path(__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, (
                f"Relative import found at line {node.lineno}: "
                f"{'.' * node.level}{node.module or ''}"
            )
    # Also verify the absolute import is present
    assert (
        "from tests.integration._helpers import" in source
    ), "Import must use absolute syntax: from tests.integration._helpers import ..."


def test_helpers_work_in_integration_context() -> None:
    """S11: Helpers work correctly when called directly (no fixture injection).

    After removing the ``inject_helpers`` fixture, calling
    ``make_mock_request`` and ``create_mock_provider_config`` via explicit
    imports must produce the same results as before.
    """
    req = make_mock_request()
    assert req is not None
    assert req.method == "POST"
    assert req.app.state is not None

    config = create_mock_provider_config()
    assert config is not None
    assert config.provider_type == "openai_like"


def test_make_mock_request_signature_preserved() -> None:
    """S12: make_mock_request signature is preserved.

    Must accept optional ``url`` and ``method`` keyword arguments
    with defaults ``http://test/v1/chat/completions`` and ``POST``.
    """
    sig = inspect.signature(make_mock_request)
    params = list(sig.parameters.keys())
    assert params == ["url", "method"], f"Expected ['url', 'method'], got {params}"

    assert sig.parameters["url"].default == "http://test/v1/chat/completions"
    assert sig.parameters["method"].default == "POST"
    assert sig.return_annotation is not None


def test_create_mock_provider_config_signature_preserved() -> None:
    """S13: create_mock_provider_config signature is preserved.

    Must accept optional keyword-only arguments: ``provider_type``,
    ``default_model``, ``streaming_mode``, ``debug_mode``, ``retry_enabled``,
    ``retry_on_key_error``, ``retry_on_server_error``.
    """
    sig = inspect.signature(create_mock_provider_config)
    params = list(sig.parameters.keys())
    expected = [
        "provider_type",
        "default_model",
        "streaming_mode",
        "debug_mode",
        "retry_enabled",
        "retry_on_key_error",
        "retry_on_server_error",
    ]
    assert params == expected, f"Expected {expected}, got {params}"

    assert sig.parameters["provider_type"].default == "openai_like"
    assert sig.parameters["default_model"].default is None
    assert sig.parameters["streaming_mode"].default == StreamingMode.AUTO
    assert sig.parameters["debug_mode"].default == DebugMode.DISABLED
    assert sig.parameters["retry_enabled"].default is False

    for name, param in sig.parameters.items():
        assert (
            param.kind == inspect.Parameter.KEYWORD_ONLY
        ), f"Parameter '{name}' should be keyword-only"
