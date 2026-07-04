"""Tests for tests/_constants.py — shared mock token constants.

Verifies that all 6 mock token constants are accessible, non-empty strings
with test-safe prefixes, and that config test files derive their ``_BASE_ENV``
from CanonicalConfig instead of hardcoding values.

Scenarios covered:
    S5: Mock tokens accessible from tests._constants.
    S6: Constants replace duplicated mock values in config test files.
"""

from __future__ import annotations

from pathlib import Path

from tests._constants import (
    MOCK_ANTHROPIC_TOKEN,
    MOCK_DEEPSEEK_TOKEN,
    MOCK_DEFAULT_TOKEN,
    MOCK_GEMINI_TOKEN,
    MOCK_METRICS_TOKEN,
    MOCK_QWEN_TOKEN,
)

# Paths to the 4 config test files that must use CanonicalConfig.
_TESTS_DIR: Path = Path(__file__).resolve().parent
_CONFIG_TEST_DIR: Path = _TESTS_DIR / "unit" / "config"

_TEST_LOADER: Path = _CONFIG_TEST_DIR / "test_loader.py"
_TEST_CONFIG_INIT: Path = _CONFIG_TEST_DIR / "test_config_init.py"
_TEST_GATEWAY_CONFIG: Path = _CONFIG_TEST_DIR / "test_gateway_config.py"
_TEST_RESOLVE_ENV_VARS: Path = _CONFIG_TEST_DIR / "test_resolve_env_vars.py"

# All 6 mock token constants as (name, value) pairs for iteration.
_ALL_TOKENS: list[tuple[str, str]] = [
    ("MOCK_GEMINI_TOKEN", MOCK_GEMINI_TOKEN),
    ("MOCK_DEEPSEEK_TOKEN", MOCK_DEEPSEEK_TOKEN),
    ("MOCK_ANTHROPIC_TOKEN", MOCK_ANTHROPIC_TOKEN),
    ("MOCK_QWEN_TOKEN", MOCK_QWEN_TOKEN),
    ("MOCK_DEFAULT_TOKEN", MOCK_DEFAULT_TOKEN),
    ("MOCK_METRICS_TOKEN", MOCK_METRICS_TOKEN),
]


def test_mock_tokens_accessible_from_constants() -> None:
    """S5: All 6 mock token constants are accessible from tests._constants.

    Verifies each constant is a string, non-empty, and starts with a
    test-safe prefix (``test_`` or ``mock_``).
    """
    for name, value in _ALL_TOKENS:
        assert isinstance(value, str), f"{name} is not a str"
        assert len(value) > 0, f"{name} is empty"
        assert value.startswith("test_") or value.startswith(
            "mock_"
        ), f"{name} does not start with 'test_' or 'mock_': {value!r}"


def test_constants_replaces_duplicated_mock_values() -> None:
    """S6: Config test files derive _BASE_ENV from CanonicalConfig.

    Verifies that the 4 config test files import from ``tests._canonical``
    and derive their env dicts from
    ``CanonicalConfig.from_example_files().to_env_dict()``
    instead of hardcoding values.
    """
    # --- test_loader.py ---
    loader_content: str = _TEST_LOADER.read_text(encoding="utf-8")
    assert "from tests._canonical import CanonicalConfig" in loader_content
    assert (
        "CanonicalConfig.from_example_files().to_env_dict()" in loader_content
    ), "test_loader.py must derive _BASE_ENV from CanonicalConfig"

    # --- test_config_init.py ---
    init_content: str = _TEST_CONFIG_INIT.read_text(encoding="utf-8")
    assert "from tests._canonical import CanonicalConfig" in init_content
    assert (
        "CanonicalConfig.from_example_files().to_env_dict()" in init_content
    ), "test_config_init.py must derive _BASE_ENV from CanonicalConfig"

    # --- test_gateway_config.py ---
    gateway_content: str = _TEST_GATEWAY_CONFIG.read_text(encoding="utf-8")
    assert "from tests._canonical import CanonicalConfig" in gateway_content
    assert (
        "CanonicalConfig.from_example_files().to_env_dict()" in gateway_content
    ), "test_gateway_config.py must derive _BASE_ENV from CanonicalConfig"

    # --- test_resolve_env_vars.py ---
    resolve_content: str = _TEST_RESOLVE_ENV_VARS.read_text(encoding="utf-8")
    assert "from tests._canonical import CanonicalConfig" in resolve_content
    assert (
        "CanonicalConfig.from_example_files().to_env_dict()" in resolve_content
    ), "test_resolve_env_vars.py must derive FULL_ENV from CanonicalConfig"
