"""Tests for canonical_config fixture and autouse env-var setup.

Verifies that the conftest.py autouse fixture ``_set_config_vars_from_canonical``
sets all 17 env vars from CanonicalConfig, and that the old
``_setup_default_env_vars`` pattern has been removed.

Scenario covered:
    S2: canonical_config fixture replaces the old setdefault pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests._canonical import CanonicalConfig
from tests._constants import (
    MOCK_ANTHROPIC_TOKEN,
    MOCK_DEEPSEEK_TOKEN,
    MOCK_DEFAULT_TOKEN,
    MOCK_GEMINI_TOKEN,
    MOCK_METRICS_TOKEN,
    MOCK_QWEN_TOKEN,
)

# All 17 env vars that the autouse fixture must set.
_ALL_ENV_VARS: list[str] = [
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "GATEWAY_HOST",
    "GATEWAY_PORT",
    "GATEWAY_WORKERS",
    "KEEPER_METRICS_PORT",
    "METRICS_ACCESS_TOKEN",
    "METRICS_BACKEND",
    "PROMETHEUS_MULTIPROC_DIR",
    "LLM_PROVIDER_DEFAULT_TOKEN",
    "GEMINI_PROD_TOKEN",
    "DEEPSEEK_TOKEN",
    "ANTHROPIC_TOKEN",
    "QWEN_HOME_TOKEN",
]

_CONFTEST_PATH: Path = Path(__file__).resolve().parent / "conftest.py"


def test_canonical_config_replaces_setdefault(
    canonical_config: CanonicalConfig,
) -> None:
    """S2: autouse fixture sets all 17 env vars from CanonicalConfig.

    Verifies that ``_set_config_vars_from_canonical`` (autouse) sets every
    env var, that DB credentials use test-safe overrides, that provider tokens
    are mock values, and that the old ``_setup_default_env_vars`` function
    no longer exists in conftest.py.

    Args:
        canonical_config: Session-scoped CanonicalConfig fixture.
    """
    # --- canonical_config fixture returns a CanonicalConfig instance ---
    assert isinstance(canonical_config, CanonicalConfig)

    # --- All 17 env vars are set in os.environ by the autouse fixture ---
    for var_name in _ALL_ENV_VARS:
        assert var_name in os.environ, f"{var_name} not set in os.environ"

    # --- DB credentials use test-safe overrides ---
    assert os.environ["DB_USER"] == "test_user"
    assert os.environ["DB_PASSWORD"] == "test_password"
    assert os.environ["DB_NAME"] == "test_db"

    # --- Token env vars are set to mock token values ---
    assert os.environ["METRICS_ACCESS_TOKEN"] == MOCK_METRICS_TOKEN
    assert os.environ["LLM_PROVIDER_DEFAULT_TOKEN"] == MOCK_DEFAULT_TOKEN
    assert os.environ["GEMINI_PROD_TOKEN"] == MOCK_GEMINI_TOKEN
    assert os.environ["DEEPSEEK_TOKEN"] == MOCK_DEEPSEEK_TOKEN
    assert os.environ["ANTHROPIC_TOKEN"] == MOCK_ANTHROPIC_TOKEN
    assert os.environ["QWEN_HOME_TOKEN"] == MOCK_QWEN_TOKEN

    # --- Old _setup_default_env_vars function no longer exists ---
    conftest_content: str = _CONFTEST_PATH.read_text(encoding="utf-8")
    assert "_setup_default_env_vars" not in conftest_content
