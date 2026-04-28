"""IT-Y06: Verify get_default_config() key order and nested structure."""

from src.config.defaults import get_default_config


def test_default_config_keys_and_values():
    """IT-Y06: get_default_config() → dict has keys in canonical order; gateway contains host, port, workers; database contains pool with min_size, max_size.

    Note: The YAML files include a 'metrics' top-level key, but get_default_config()
    does not yet include 'metrics' in its defaults (see comment in defaults.py).
    The canonical key order in defaults is: logging, gateway, worker, database, providers.
    """
    defaults = get_default_config()

    # Verify top-level key order (metrics is not in defaults yet)
    expected_keys = ["logging", "gateway", "worker", "database", "providers"]
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
    assert gateway["host"] == "0.0.0.0"
    assert gateway["port"] == 55300
    assert gateway["workers"] == 4

    # Verify database contains pool with min_size, max_size
    assert "database" in defaults
    database = defaults["database"]
    assert "pool" in database
    pool = database["pool"]
    assert "min_size" in pool
    assert "max_size" in pool
    assert pool["min_size"] == 1
    assert pool["max_size"] == 15
