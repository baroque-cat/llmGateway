"""Shared test constants. Import-safe from any test file.

This module centralises mock token values that were previously duplicated
across ``tests/conftest.py`` and individual ``_BASE_ENV`` dictionaries in
config test files.  Importing this module has no side effects.
"""

MOCK_GEMINI_TOKEN: str = "test_gemini_token"
MOCK_DEEPSEEK_TOKEN: str = "test_deepseek_token"
MOCK_ANTHROPIC_TOKEN: str = "test_anthropic_token"
MOCK_QWEN_TOKEN: str = "test_qwen_token"
MOCK_DEFAULT_TOKEN: str = "test_token"
MOCK_METRICS_TOKEN: str = "test_metrics_token"
