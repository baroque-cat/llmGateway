#!/usr/bin/env python3

"""
Unit tests for main.py error handling in _start_gateway_service and _start_keeper_service.

Verifies that both service starters exit with SystemExit(1) when:
- load_config raises FileNotFoundError
- load_config raises ValueError
- load_config raises a generic Exception
"""

import argparse
from unittest.mock import patch

import pytest

import main


class TestStartGatewayErrorHandling:
    """Tests for _start_gateway_service error handling."""

    def test_start_gateway_file_not_found_exits_1(self) -> None:
        """ERR-GW-01: load_config → FileNotFoundError → SystemExit(1)."""
        args = argparse.Namespace(host=None, port=None, workers=None)
        with (
            patch(
                "main.load_config",
                side_effect=FileNotFoundError("config.yaml not found"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main._start_gateway_service(args)
            assert exc_info.value.code == 1

    def test_start_gateway_value_error_exits_1(self) -> None:
        """ERR-GW-02: load_config → ValueError → SystemExit(1)."""
        args = argparse.Namespace(host=None, port=None, workers=None)
        with (
            patch("main.load_config", side_effect=ValueError("Invalid config value")),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main._start_gateway_service(args)
            assert exc_info.value.code == 1

    def test_start_gateway_generic_exception_exits_1(self) -> None:
        """ERR-GW-03: load_config → Exception → SystemExit(1)."""
        args = argparse.Namespace(host=None, port=None, workers=None)
        with (patch("main.load_config", side_effect=Exception("Unexpected error")),):
            with pytest.raises(SystemExit) as exc_info:
                main._start_gateway_service(args)
            assert exc_info.value.code == 1


class TestStartKeeperErrorHandling:
    """Tests for _start_keeper_service error handling."""

    @pytest.mark.asyncio
    async def test_start_keeper_file_not_found_exits_1(self) -> None:
        """ERR-KP-01: load_config → FileNotFoundError → SystemExit(1)."""
        with (
            patch(
                "main.load_config",
                side_effect=FileNotFoundError("config.yaml not found"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await main._start_keeper_service()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_start_keeper_value_error_exits_1(self) -> None:
        """ERR-KP-02: load_config → ValueError → SystemExit(1)."""
        with (
            patch("main.load_config", side_effect=ValueError("Invalid config value")),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await main._start_keeper_service()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_start_keeper_generic_exception_exits_1(self) -> None:
        """ERR-KP-03: load_config → Exception → SystemExit(1)."""
        with (patch("main.load_config", side_effect=Exception("Unexpected error")),):
            with pytest.raises(SystemExit) as exc_info:
                await main._start_keeper_service()
            assert exc_info.value.code == 1
