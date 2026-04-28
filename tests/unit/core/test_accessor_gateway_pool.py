"""Unit tests for ConfigAccessor gateway and pool configuration methods.

Tests cover the new accessor methods introduced in the gateway-pool-config change:
  - get_gateway_config, get_gateway_host, get_gateway_port, get_gateway_workers
  - get_pool_config

Test IDs: UT-A01 through UT-A07.
"""

import pytest

from src.config.schemas import Config, DatabasePoolConfig, GatewayConfig
from src.core.accessor import ConfigAccessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def default_accessor() -> ConfigAccessor:
    """ConfigAccessor backed by a default (empty) Config."""
    return ConfigAccessor(Config())


# ---------------------------------------------------------------------------
# UT-A01: get_gateway_config returns GatewayConfig with defaults
# ---------------------------------------------------------------------------


def test_get_gateway_config_returns_default_gateway_config(
    default_accessor: ConfigAccessor,
) -> None:
    """UT-A01: ConfigAccessor(Config()).get_gateway_config() → GatewayConfig with defaults."""
    gw = default_accessor.get_gateway_config()
    assert isinstance(gw, GatewayConfig)
    assert gw.host == "0.0.0.0"
    assert gw.port == 55300
    assert gw.workers == 4


# ---------------------------------------------------------------------------
# UT-A02: get_gateway_host returns default host
# ---------------------------------------------------------------------------


def test_get_gateway_host_default(default_accessor: ConfigAccessor) -> None:
    """UT-A02: ConfigAccessor(Config()).get_gateway_host() == '0.0.0.0'."""
    assert default_accessor.get_gateway_host() == "0.0.0.0"


# ---------------------------------------------------------------------------
# UT-A03: get_gateway_port returns default port
# ---------------------------------------------------------------------------


def test_get_gateway_port_default(default_accessor: ConfigAccessor) -> None:
    """UT-A03: ConfigAccessor(Config()).get_gateway_port() == 55300."""
    assert default_accessor.get_gateway_port() == 55300


# ---------------------------------------------------------------------------
# UT-A04: get_gateway_workers returns default workers count
# ---------------------------------------------------------------------------


def test_get_gateway_workers_default(default_accessor: ConfigAccessor) -> None:
    """UT-A04: ConfigAccessor(Config()).get_gateway_workers() == 4."""
    assert default_accessor.get_gateway_workers() == 4


# ---------------------------------------------------------------------------
# UT-A05: get_gateway_workers with custom workers override
# ---------------------------------------------------------------------------


def test_get_gateway_workers_custom() -> None:
    """UT-A05: ConfigAccessor(Config.model_validate({'gateway': {'workers': 2}})).get_gateway_workers() == 2."""
    cfg = Config.model_validate({"gateway": {"workers": 2}})
    accessor = ConfigAccessor(cfg)
    assert accessor.get_gateway_workers() == 2


# ---------------------------------------------------------------------------
# UT-A06: get_pool_config returns DatabasePoolConfig with defaults
# ---------------------------------------------------------------------------


def test_get_pool_config_returns_default_pool_config(
    default_accessor: ConfigAccessor,
) -> None:
    """UT-A06: ConfigAccessor(Config()).get_pool_config() → DatabasePoolConfig with defaults min_size=1, max_size=15."""
    pool = default_accessor.get_pool_config()
    assert isinstance(pool, DatabasePoolConfig)
    assert pool.min_size == 1
    assert pool.max_size == 15


# ---------------------------------------------------------------------------
# UT-A07: get_pool_config with custom pool overrides
# ---------------------------------------------------------------------------


def test_get_pool_config_custom() -> None:
    """UT-A07: ConfigAccessor(Config.model_validate({'database': {'pool': {'min_size': 2, 'max_size': 10}}}))
    .get_pool_config().min_size == 2, max_size == 10."""
    cfg = Config.model_validate({"database": {"pool": {"min_size": 2, "max_size": 10}}})
    accessor = ConfigAccessor(cfg)
    pool = accessor.get_pool_config()
    assert pool.min_size == 2
    assert pool.max_size == 10
