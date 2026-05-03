"""Tests for defaults.py: env var references, key order, and structure.

Merged from test_defaults_env_vars.py and test_defaults_order.py to eliminate
duplication of gateway env-var value assertions (UT-EV02 vs key-order test).

Test IDs:
  UT-EV01 – All database parameters are ${VAR} references
  UT-EV02 – All gateway parameters are ${VAR} references
  UT-EV03 – Hardcoded constants (logging, pool, retry, keeper) remain
  UT-EV04 – No hardcoded operational values exist
  IT-Y06  – Default config key order and nested structure
  IT-Y07-1 – dedicated_http_client defaults to False
  IT-Y05  – Full config YAML key order (moved from integration)
"""

from ruamel.yaml import YAML

from src.config.defaults import get_default_config


# --- Env Var Tests ---


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


# --- Key Order Tests ---


def test_default_config_keys_and_values():
    """IT-Y06: get_default_config() → dict has keys in canonical order; gateway contains host, port, workers keys; database contains pool with min_size, max_size.

    Note: The YAML files include a 'metrics' top-level key, but get_default_config()
    does not yet include 'metrics' in its defaults (see comment in defaults.py).
    The canonical key order in defaults is: logging, gateway, keeper, database, providers.

    Gateway env-var VALUES are verified by test_ut_ev02 above, so this test
    only checks key EXISTENCE for gateway (not value equality) to avoid duplication.
    """
    defaults = get_default_config()

    # Verify top-level key order (metrics is not in defaults yet)
    expected_keys = ["logging", "gateway", "keeper", "database", "providers"]
    actual_keys = list(defaults.keys())
    assert (
        actual_keys == expected_keys
    ), f"Key order mismatch: got {actual_keys}, expected {expected_keys}"

    # Verify gateway contains host, port, workers keys (values tested in UT-EV02)
    assert "gateway" in defaults
    gateway = defaults["gateway"]
    assert "host" in gateway
    assert "port" in gateway
    assert "workers" in gateway

    # Verify database contains pool with min_size, max_size
    assert "database" in defaults
    database = defaults["database"]
    assert "pool" in database
    pool = database["pool"]
    assert "min_size" in pool
    assert "max_size" in pool
    assert pool["min_size"] == 1
    assert pool["max_size"] == 15


def test_default_config_dedicated_http_client():
    """IT-Y07-1: get_default_config()['providers']['llm_provider_default'] contains
    'dedicated_http_client' key with value False."""
    defaults = get_default_config()

    assert "providers" in defaults
    llm_default = defaults["providers"]["llm_provider_default"]

    # Verify the dedicated_http_client key exists and is False
    assert "dedicated_http_client" in llm_default, (
        f"Key 'dedicated_http_client' not found in llm_provider_default. "
        f"Available keys: {list(llm_default.keys())}"
    )
    assert (
        llm_default["dedicated_http_client"] is False
    ), f"Expected dedicated_http_client=False, got {llm_default['dedicated_http_client']}"


# --- Test moved from integration/test_config_examples.py ---


def test_full_config_key_order():
    """IT-Y05: Read example_full_config.yaml as dict → keys in order:
    logging, metrics, gateway, worker, database, providers.

    Moved from integration/test_config_examples.py — this test only reads
    a YAML file as a dict (unit test, no gateway/keeper dependency).
    """
    yaml = YAML()
    with open("config/example_full_config.yaml", encoding="utf-8") as f:
        data = yaml.load(f)
    expected_order = [
        "logging",
        "metrics",
        "gateway",
        "keeper",
        "database",
        "providers",
    ]
    assert list(data.keys()) == expected_order