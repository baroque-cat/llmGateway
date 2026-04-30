# tests/unit/test_main_cli.py
"""Unit tests for CLI override logic in main.py.

Test IDs:
  UT-CLI01 – argparse defaults (host/port/workers all None)
  UT-CLI02 – CLI --workers overrides config
  UT-CLI03 – CLI without --port keeps config default
  UT-CLI04 – CLI without --workers keeps config default
  UT-CLI05 – CLI --host overrides config
  UT-CLI06 – CLI --port overrides config
  UT-CLI07 – uvicorn.run receives config values after overrides
  IT-S03  – validate_pool_sizing called before uvicorn.run in gateway
  IT-S04  – validate_pool_sizing called before run_keeper in keeper
  SEC-07  – argparse default=None, not old argparse default (8000)
"""

import argparse
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from src.config.schemas import Config

# ---------------------------------------------------------------------------
# UT-CLI01: argparse defaults
# ---------------------------------------------------------------------------


def test_cli01_argparse_defaults():
    """UT-CLI01: argparse for gateway: --host default=None, --port default=None, --workers default=None"""
    with (
        patch("main._start_gateway_service") as mock_start,
        patch.object(sys, "argv", ["main.py", "gateway"]),
    ):
        main.main()

    args = mock_start.call_args[0][0]
    assert args.host is None, "--host default should be None"
    assert args.port is None, "--port default should be None"
    assert args.workers is None, "--workers default should be None"


# ---------------------------------------------------------------------------
# UT-CLI02: CLI --workers overrides config
# ---------------------------------------------------------------------------


def test_cli02_workers_override():
    """UT-CLI02: Mock load_config → Config with gateway.workers=4, CLI --workers 8 → final config.gateway.workers == 8"""
    config = Config()
    assert config.gateway.workers == 4  # sanity: default is 4

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host=None, port=None, workers=8)
        main._start_gateway_service(args)

    assert config.gateway.workers == 8


# ---------------------------------------------------------------------------
# UT-CLI03: CLI without --port keeps config default
# ---------------------------------------------------------------------------


def test_cli03_port_config_default():
    """UT-CLI03: Mock load_config → Config with gateway.port=55300, CLI without --port → final config.gateway.port == 55300"""
    config = Config()
    assert config.gateway.port == 55300  # sanity: default is 55300

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host=None, port=None, workers=None)
        main._start_gateway_service(args)

    assert config.gateway.port == 55300


# ---------------------------------------------------------------------------
# UT-CLI04: CLI without --workers keeps config default
# ---------------------------------------------------------------------------


def test_cli04_workers_config_default():
    """UT-CLI04: Mock load_config → Config with default gateway.workers=4, CLI without --workers → final config.gateway.workers == 4"""
    config = Config()
    assert config.gateway.workers == 4  # sanity: default is 4

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host=None, port=None, workers=None)
        main._start_gateway_service(args)

    assert config.gateway.workers == 4


# ---------------------------------------------------------------------------
# UT-CLI05: CLI --host overrides config
# ---------------------------------------------------------------------------


def test_cli05_host_override():
    """UT-CLI05: CLI --host 127.0.0.1 overrides config default host 0.0.0.0."""
    config = Config()
    assert config.gateway.host == "0.0.0.0"  # sanity: default is 0.0.0.0

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host="127.0.0.1", port=None, workers=None)
        main._start_gateway_service(args)

    assert config.gateway.host == "127.0.0.1"


# ---------------------------------------------------------------------------
# UT-CLI06: CLI --port overrides config
# ---------------------------------------------------------------------------


def test_cli06_port_override():
    """UT-CLI06: Mock load_config → Config with gateway.port=55300, CLI --port 8080 → final config.gateway.port == 8080"""
    config = Config()
    assert config.gateway.port == 55300  # sanity: default is 55300

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host=None, port=8080, workers=None)
        main._start_gateway_service(args)

    assert config.gateway.port == 8080


# ---------------------------------------------------------------------------
# UT-CLI07: uvicorn.run receives config values after overrides
# ---------------------------------------------------------------------------


def test_cli07_uvicorn_run_args():
    """UT-CLI07: _start_gateway_service(args) calls uvicorn.run(app, host=config.gateway.host, port=config.gateway.port, workers=config.gateway.workers)"""
    config = Config()
    mock_app = MagicMock()

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn") as mock_uvicorn,
        patch("main.create_app", return_value=mock_app),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args = argparse.Namespace(host="192.168.1.1", port=9090, workers=2)
        main._start_gateway_service(args)

    mock_uvicorn.run.assert_called_once_with(
        mock_app,
        host="192.168.1.1",
        port=9090,
        workers=2,
        access_log=False,
    )


# ---------------------------------------------------------------------------
# IT-S03: validate_pool_sizing called before uvicorn.run in gateway
# ---------------------------------------------------------------------------


def test_it_s03_validate_before_uvicorn():
    """IT-S03: Mock validate_pool_sizing → _start_gateway_service calls validate_pool_sizing(config) before uvicorn.run"""
    call_order: list[str] = []
    config = Config()

    def track_validate(c: Config) -> None:
        call_order.append("validate")

    def track_uvicorn(*a, **k) -> None:
        call_order.append("uvicorn")

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn") as mock_uvicorn,
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing") as mock_validate,
    ):
        mock_validate.side_effect = track_validate
        mock_uvicorn.run.side_effect = track_uvicorn

        args = argparse.Namespace(host=None, port=None, workers=None)
        main._start_gateway_service(args)

    assert call_order == [
        "validate",
        "uvicorn",
    ], f"validate_pool_sizing must be called before uvicorn.run; got {call_order}"


# ---------------------------------------------------------------------------
# IT-S04: validate_pool_sizing called before run_worker in worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_s04_validate_before_worker():
    """IT-S04: Mock validate_pool_sizing → _start_keeper_service calls validate_pool_sizing(config) before run_keeper"""
    call_order: list[str] = []
    config = Config()

    def track_validate(c: Config) -> None:
        call_order.append("validate")

    async def track_run_keeper() -> None:
        call_order.append("run_keeper")

    with (
        patch("main.load_config", return_value=config),
        patch("main.validate_pool_sizing") as mock_validate,
        patch("main.run_keeper", new_callable=AsyncMock) as mock_run_keeper,
    ):
        mock_validate.side_effect = track_validate
        mock_run_keeper.side_effect = track_run_keeper

        await main._start_keeper_service()

    assert call_order == [
        "validate",
        "run_keeper",
    ], f"validate_pool_sizing must be called before run_keeper; got {call_order}"


# ---------------------------------------------------------------------------
# SEC-07: argparse default=None, not old argparse default
# ---------------------------------------------------------------------------


def test_sec07_no_old_argparse_port_default():
    """SEC-07: argparse default=None means old argparse default (8000 for port) is NOT applied when CLI not passed."""
    # Part A: argparse --port default is None (not 8000 or any other value)
    with (
        patch("main._start_gateway_service") as mock_start,
        patch.object(sys, "argv", ["main.py", "gateway"]),
    ):
        main.main()

    args = mock_start.call_args[0][0]
    assert (
        args.port is None
    ), "argparse --port default should be None, not 8000 or any other value"

    # Part B: when CLI --port is not passed, config default (55300) is preserved
    config = Config()
    assert config.gateway.port == 55300

    with (
        patch("main.load_config", return_value=config),
        patch("main.uvicorn"),
        patch("main.create_app", return_value=MagicMock()),
        patch("main.setup_logging"),
        patch("main.validate_pool_sizing"),
    ):
        args_no_port = argparse.Namespace(host=None, port=None, workers=None)
        main._start_gateway_service(args_no_port)

    assert (
        config.gateway.port == 55300
    ), "Config port should remain 55300, not be overridden by any argparse default"
