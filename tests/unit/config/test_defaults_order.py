"""IT-Y06: Verify get_default_config() key order and nested structure."""

from src.config.defaults import get_default_config


def test_default_config_keys_and_values():
    """IT-Y06: get_default_config() → dict has keys in canonical order; gateway contains host, port, workers; database contains pool with min_size, max_size.

    Note: The YAML files include a 'metrics' top-level key, but get_default_config()
    does not yet include 'metrics' in its defaults (see comment in defaults.py).
    The canonical key order in defaults is: logging, gateway, keeper, database, providers.
    """
    defaults = get_default_config()

    # Verify top-level key order (metrics is not in defaults yet)
    expected_keys = ["logging", "gateway", "keeper", "database", "providers"]
    actual_keys = list(defaults.keys())
    assert (
        actual_keys == expected_keys
    ), f"Key order mismatch: got {actual_keys}, expected {expected_keys}"

    # Verify gateway contains host, port, workers
    assert "gateway" in defaults
    gateway = defaults["gateway"]
    assert "host" in gateway
    assert "port" in gateway
    assert "workers" in gateway
    assert gateway["host"] == "${GATEWAY_HOST}"
    assert gateway["port"] == "${GATEWAY_PORT}"
    assert gateway["workers"] == "${GATEWAY_WORKERS}"

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
