"""Tests for _resolve_env_vars and ConfigLoader env var resolution (UT-EV05–UT-EV12)."""

import os
from unittest.mock import mock_open, patch

import pytest

from src.config.defaults import get_default_config
from src.config.loader import ConfigLoader

# ---------------------------------------------------------------------------
# UT-EV05: Missing DB_HOST produces clear error
# ---------------------------------------------------------------------------


def test_ut_ev05_missing_db_host_raises_value_error() -> None:
    """UT-EV05: Missing DB_HOST → ValueError with message about unset variable."""
    # Clear DB_HOST if set, to test the missing case
    with patch.dict(os.environ, {}, clear=True):
        loader = ConfigLoader.__new__(ConfigLoader)
        with pytest.raises(ValueError, match="DB_HOST.*is not set"):
            loader._resolve_env_vars({"host": "${DB_HOST}"})


def test_ut_ev06_missing_gateway_workers_raises_value_error() -> None:
    """UT-EV06: Missing GATEWAY_WORKERS → ValueError with message about unset variable."""
    with patch.dict(os.environ, {}, clear=True):
        loader = ConfigLoader.__new__(ConfigLoader)
        with pytest.raises(ValueError, match="GATEWAY_WORKERS.*is not set"):
            loader._resolve_env_vars({"workers": "${GATEWAY_WORKERS}"})


def test_ut_ev07_missing_env_var_blocks_startup() -> None:
    """UT-EV07: ConfigLoader.load() with defaults and empty env → ValueError."""
    yaml_content = (
        "providers:\n  test_provider:\n    provider_type: gemini\n    enabled: true\n"
    )
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        with pytest.raises(ValueError, match="is not set"):
            loader.load()


# ---------------------------------------------------------------------------
# UT-EV08: GatewayConfig with env vars (positive)
# ---------------------------------------------------------------------------

FULL_ENV: dict[str, str] = {
    "DB_HOST": "database",
    "DB_PORT": "5432",
    "DB_USER": "llm_gateway",
    "DB_PASSWORD": "secret",
    "DB_NAME": "llmgateway",
    "GATEWAY_HOST": "0.0.0.0",
    "GATEWAY_PORT": "55300",
    "GATEWAY_WORKERS": "4",
    "LLM_PROVIDER_DEFAULT_TOKEN": "test_token",
}


def test_ut_ev08_gateway_config_with_env_vars() -> None:
    """UT-EV08: All env vars set → gateway.host/port/workers are correct."""
    yaml_content = (
        "providers:\n  test_provider:\n    provider_type: gemini\n    enabled: true\n"
    )
    with (
        patch.dict(os.environ, FULL_ENV),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        config = loader.load()
        assert config.gateway.host == "0.0.0.0"
        assert config.gateway.port == 55300
        assert config.gateway.workers == 4


def test_ut_ev09_missing_gateway_workers_blocks_startup() -> None:
    """UT-EV09: ConfigLoader.load() without GATEWAY_WORKERS → ValueError."""
    env = {k: v for k, v in FULL_ENV.items() if k != "GATEWAY_WORKERS"}
    yaml_content = (
        "providers:\n  test_provider:\n    provider_type: gemini\n    enabled: true\n"
    )
    with (
        patch.dict(os.environ, env, clear=True),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        loader = ConfigLoader(path="dummy.yaml")
        with pytest.raises(ValueError, match="GATEWAY_WORKERS.*is not set"):
            loader.load()


def test_ut_ev10_all_env_vars_resolved() -> None:
    """UT-EV10: _resolve_env_vars on full defaults with all env vars → all ${VAR} replaced."""
    with patch.dict(os.environ, FULL_ENV):
        loader = ConfigLoader.__new__(ConfigLoader)
        defaults = get_default_config()
        resolved = loader._resolve_env_vars(defaults)
        assert resolved["database"]["host"] == "database"
        assert resolved["database"]["port"] == "5432"
        assert resolved["database"]["user"] == "llm_gateway"
        assert resolved["database"]["password"] == "secret"
        assert resolved["database"]["dbname"] == "llmgateway"
        assert resolved["gateway"]["host"] == "0.0.0.0"
        assert resolved["gateway"]["port"] == "55300"
        assert resolved["gateway"]["workers"] == "4"
        # Provider token should also be resolved
        assert (
            resolved["providers"]["llm_provider_default"]["access_control"][
                "gateway_access_token"
            ]
            == "test_token"
        )


def test_ut_ev11_partial_missing_env_vars() -> None:
    """UT-EV11: Missing DB_HOST and DB_PORT → ValueError on first missing (DB_HOST)."""
    env = {k: v for k, v in FULL_ENV.items() if k not in ("DB_HOST", "DB_PORT")}
    with patch.dict(os.environ, env, clear=True):
        loader = ConfigLoader.__new__(ConfigLoader)
        with pytest.raises(ValueError, match="DB_HOST.*is not set"):
            loader._resolve_env_vars(get_default_config())


def test_ut_ev12_empty_env_var_value() -> None:
    """UT-EV12: DB_HOST="" in env → _resolve_env_vars replaces ${DB_HOST} with "" (empty string)."""
    with patch.dict(os.environ, {"DB_HOST": ""}):
        loader = ConfigLoader.__new__(ConfigLoader)
        result = loader._resolve_env_vars({"host": "${DB_HOST}"})
        assert result["host"] == ""
