"""Tests for defaults.py env var references (UT-EV01–UT-EV04).

Test IDs:
  UT-EV01 – All database parameters are ${VAR} references
  UT-EV02 – All gateway parameters are ${VAR} references
  UT-EV03 – Hardcoded constants (logging, pool, retry, keeper) remain
  UT-EV04 – No hardcoded operational values exist
"""

from src.config.defaults import get_default_config


def test_ut_ev01_database_params_are_env_vars() -> None:
    """UT-EV01: All database params in defaults.py are ${VAR} references."""
    defaults = get_default_config()
    db = defaults["database"]
    assert db["host"] == "${DB_HOST}"
    assert db["port"] == "${DB_PORT}"
    assert db["user"] == "${DB_USER}"
    assert db["password"] == "${DB_PASSWORD}"
    assert db["dbname"] == "${DB_NAME}"


def test_ut_ev02_gateway_params_are_env_vars() -> None:
    """UT-EV02: All gateway params in defaults.py are ${VAR} references."""
    defaults = get_default_config()
    gw = defaults["gateway"]
    assert gw["host"] == "${GATEWAY_HOST}"
    assert gw["port"] == "${GATEWAY_PORT}"
    assert gw["workers"] == "${GATEWAY_WORKERS}"


def test_ut_ev03_hardcoded_constants_remain() -> None:
    """UT-EV03: Hardcoded constants (logging, pool, retry, keeper) are NOT replaced with ${VAR}."""
    defaults = get_default_config()
    assert defaults["logging"]["level"] == "INFO"
    assert defaults["database"]["pool"]["min_size"] == 1
    assert defaults["database"]["pool"]["max_size"] == 15
    assert defaults["database"]["retry"]["max_attempts"] == 3
    assert defaults["keeper"]["max_concurrent_providers"] == 10


def test_ut_ev04_no_hardcoded_operational_values() -> None:
    """UT-EV04: No hardcoded operational values — only ${VAR} references for host/port/user/password/dbname/workers."""
    defaults = get_default_config()
    operational_keys: list[tuple[str, str]] = [
        ("database", "host"),
        ("database", "port"),
        ("database", "user"),
        ("database", "password"),
        ("database", "dbname"),
        ("gateway", "host"),
        ("gateway", "port"),
        ("gateway", "workers"),
    ]
    for path in operational_keys:
        value = defaults[path[0]][path[1]]
        assert isinstance(value, str) and value.startswith(
            "${"
        ), f"Operational key {path} has hardcoded value {value}, expected ${{VAR}} reference"
