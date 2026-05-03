#!/usr/bin/env python3

"""
Tests for module-level app in main.py.

Verifies that importing main.py creates the module-level ``app`` correctly,
with proper calls to load_config, setup_logging, and create_app, and that
the __main__ block runs uvicorn correctly.

Test IDs:
  UT-M01: main.app exists and is a FastAPI instance
  UT-M02: load_config() is called during import
  UT-M03: setup_logging() is called during import
  UT-M04: create_app() is called during import
  UT-M05: __main__ block runs uvicorn.run(app, workers=1)
  UT-M06: config.gateway.workers > 1 → __main__ still uses workers=1
"""

import runpy
import sys
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
import pytest


def _remove_main_from_sys_modules() -> None:
    """Remove 'main' from sys.modules to force a fresh import on next access."""
    for key in list(sys.modules):
        if key == "main" or key.startswith("main."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# UT-M01 through UT-M04: Module-level app creation on import
# ---------------------------------------------------------------------------


class TestModuleLevelApp:
    """Tests for module-level app creation when main.py is imported."""

    @pytest.fixture(autouse=True)
    def _cleanup_main_module(self) -> Generator[None, None, None]:
        """Remove 'main' from sys.modules before and after each test."""
        _remove_main_from_sys_modules()
        yield
        _remove_main_from_sys_modules()

    def test_ut_m01_app_exists_and_is_fastapi_instance(self) -> None:
        """UT-M01: import main → main.app exists and is a FastAPI instance."""
        mock_config = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
        ):
            import main  # noqa: F811

            # main.app must exist as a module-level attribute
            assert hasattr(main, "app"), "main.app attribute must exist after import"

            # main.app must be the object returned by create_app()
            assert main.app is mock_app, "main.app must be the return value of create_app()"

            # Verify the mock was created with FastAPI spec (confirms intended type)
            assert mock_app._spec_class is FastAPI

    def test_ut_m02_load_config_called_on_import(self) -> None:
        """UT-M02: import main → load_config() is called during import."""
        mock_config = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config) as mock_load,
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
        ):
            import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

            mock_load.assert_called_once()

    def test_ut_m03_setup_logging_called_on_import(self) -> None:
        """UT-M03: import main → setup_logging() is called during import."""
        mock_config = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging") as mock_setup,
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
        ):
            import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

            # setup_logging must be called with the ConfigAccessor instance
            mock_setup.assert_called_once_with(mock_accessor)

    def test_ut_m04_create_app_called_on_import(self) -> None:
        """UT-M04: import main → create_app() is called during import."""
        mock_config = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app) as mock_create,
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
        ):
            import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

            # create_app must be called with the ConfigAccessor instance
            mock_create.assert_called_once_with(mock_accessor)


# ---------------------------------------------------------------------------
# UT-M05 and UT-M06: __main__ block behavior
# ---------------------------------------------------------------------------


class TestMainBlock:
    """Tests for the __main__ block in main.py (local development entry point)."""

    @pytest.fixture(autouse=True)
    def _cleanup_main_module(self) -> Generator[None, None, None]:
        """Remove 'main' from sys.modules before and after each test."""
        _remove_main_from_sys_modules()
        yield
        _remove_main_from_sys_modules()

    def test_ut_m05_main_block_runs_uvicorn_with_workers_1(self) -> None:
        """UT-M05: python main.py → __main__ block runs uvicorn.run(app, workers=1)."""
        mock_config = MagicMock()
        mock_config.gateway.host = "0.0.0.0"
        mock_config.gateway.port = 8000
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
            patch("uvicorn.run") as mock_uvicorn_run,
            patch.object(sys, "argv", ["main.py"]),
        ):
            # runpy.run_path executes main.py with __name__ == "__main__"
            runpy.run_path("main.py", run_name="__main__")

            mock_uvicorn_run.assert_called_once()

            # Verify uvicorn.run was called with the module-level app
            call_args = mock_uvicorn_run.call_args
            assert call_args.args[0] is mock_app, (
                "uvicorn.run first positional arg must be the module-level app"
            )

            # Verify keyword arguments match expected __main__ block values
            call_kwargs = call_args.kwargs
            assert call_kwargs["workers"] == 1, "workers must be 1 in __main__ block"
            assert call_kwargs["host"] == "0.0.0.0", "host must come from config.gateway.host"
            assert call_kwargs["port"] == 8000, "port must come from config.gateway.port"
            assert call_kwargs["access_log"] is False, "access_log must be False"

    def test_ut_m05_main_block_keeper_arg_runs_keeper(self) -> None:
        """UT-M05 (supplementary): python main.py keeper → asyncio.run(run_keeper())."""
        mock_config = MagicMock()
        mock_config.gateway.host = "0.0.0.0"
        mock_config.gateway.port = 8000
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
            patch("uvicorn.run") as mock_uvicorn_run,
            patch("src.services.keeper.run_keeper", new_callable=AsyncMock) as mock_keeper,
            patch.object(sys, "argv", ["main.py", "keeper"]),
        ):
            runpy.run_path("main.py", run_name="__main__")

            # When argv[1] == "keeper", run_keeper is called, uvicorn.run is NOT
            mock_keeper.assert_called_once()
            mock_uvicorn_run.assert_not_called()

    def test_ut_m06_config_workers_gt_1_main_block_still_uses_workers_1(self) -> None:
        """UT-M06: When config.gateway.workers > 1, __main__ block still uses workers=1.

        The __main__ block hardcodes workers=1 for local development regardless
        of the config value. A warning log when config.gateway.workers > 1 is
        a recommended future enhancement but is not currently implemented.
        """
        mock_config = MagicMock()
        mock_config.gateway.host = "0.0.0.0"
        mock_config.gateway.port = 8000
        mock_config.gateway.workers = 4  # Config says 4 workers
        mock_app = MagicMock(spec=FastAPI)
        mock_accessor = MagicMock()

        with (
            patch("src.config.load_config", return_value=mock_config),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=mock_app),
            patch("src.core.accessor.ConfigAccessor", return_value=mock_accessor),
            patch("uvicorn.run") as mock_uvicorn_run,
            patch.object(sys, "argv", ["main.py"]),
        ):
            runpy.run_path("main.py", run_name="__main__")

            mock_uvicorn_run.assert_called_once()
            call_kwargs = mock_uvicorn_run.call_args.kwargs

            # The __main__ block hardcodes workers=1 regardless of config
            assert call_kwargs["workers"] == 1, (
                "__main__ block must use workers=1 for local development, "
                "even when config.gateway.workers > 1"
            )