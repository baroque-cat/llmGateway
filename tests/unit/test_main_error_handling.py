#!/usr/bin/env python3

"""
Unit tests for main.py error handling during module import.

Verifies that importing main.py fails appropriately when config loading
or validation raises errors. Since the refactoring moved config loading
to module-level (executed on every import), config errors now block the
entire module import rather than being caught in service-start functions.

Test IDs:
  ERR-01: load_config → FileNotFoundError → import fails with FileNotFoundError
  ERR-02: load_config → ValueError → import fails with ValueError
  ERR-03: load_config → SystemExit(1) (Pydantic validation) → import fails with SystemExit(1)
  ERR-04: load_config → generic Exception → import fails with that Exception
  ERR-05: successful import after previous failure (module cleanup works)
"""

import sys
from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
import pytest


def _remove_main_from_sys_modules() -> None:
    """Remove 'main' from sys.modules to force a fresh import on next access."""
    for key in list(sys.modules):
        if key == "main" or key.startswith("main."):
            del sys.modules[key]


class TestConfigErrorBlocksModuleImport:
    """Tests that config loading errors block the import of main.py.

    After the module-level app refactoring, load_config() is called at
    import time. If it raises an exception, the entire import fails —
    there is no try/except wrapping at module level.
    """

    @pytest.fixture(autouse=True)
    def _cleanup_main_module(self) -> Generator[None, None, None]:
        """Remove 'main' from sys.modules before and after each test."""
        _remove_main_from_sys_modules()
        yield
        _remove_main_from_sys_modules()

    def test_err_01_file_not_found_blocks_import(self) -> None:
        """ERR-01: load_config → FileNotFoundError → import raises FileNotFoundError."""
        with (
            patch(
                "src.config.load_config",
                side_effect=FileNotFoundError("config.yaml not found"),
            ),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=MagicMock(spec=FastAPI)),
            patch("src.core.accessor.ConfigAccessor", return_value=MagicMock()),
        ):
            with pytest.raises(FileNotFoundError, match="config.yaml not found"):
                import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

    def test_err_02_value_error_blocks_import(self) -> None:
        """ERR-02: load_config → ValueError → import raises ValueError."""
        with (
            patch("src.config.load_config", side_effect=ValueError("Invalid config value")),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=MagicMock(spec=FastAPI)),
            patch("src.core.accessor.ConfigAccessor", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="Invalid config value"):
                import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

    def test_err_03_system_exit_1_blocks_import(self) -> None:
        """ERR-03: load_config → SystemExit(1) (Pydantic validation error) → import raises SystemExit(1).

        In the real application, Pydantic model_validator raises ValueError,
        which is caught by ConfigLoader.load() as ValidationError, then
        handle_validation_error() calls sys.exit(1). This test simulates
        that flow by having load_config raise SystemExit(1) directly.
        """
        with (
            patch("src.config.load_config", side_effect=SystemExit(1)),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=MagicMock(spec=FastAPI)),
            patch("src.core.accessor.ConfigAccessor", return_value=MagicMock()),
        ):
            with pytest.raises(SystemExit) as exc_info:
                import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

            assert exc_info.value.code == 1, "SystemExit code must be 1 for config validation failure"

    def test_err_04_generic_exception_blocks_import(self) -> None:
        """ERR-04: load_config → generic Exception → import raises that Exception."""
        with (
            patch("src.config.load_config", side_effect=Exception("Unexpected error")),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=MagicMock(spec=FastAPI)),
            patch("src.core.accessor.ConfigAccessor", return_value=MagicMock()),
        ):
            with pytest.raises(Exception, match="Unexpected error"):
                import main  # pyright: ignore[reportUnusedImport]  # noqa: F811

    def test_err_05_successful_import_after_previous_failure(self) -> None:
        """ERR-05: After a failed import, removing main from sys.modules allows a successful re-import.

        This verifies that the _remove_main_from_sys_modules cleanup works
        correctly, enabling subsequent tests to import main fresh.
        """
        # First: simulate a failed import
        with (
            patch("src.config.load_config", side_effect=FileNotFoundError("not found")),
            patch("src.config.logging_config.setup_logging"),
            patch("src.services.gateway.gateway_service.create_app", return_value=MagicMock(spec=FastAPI)),
            patch("src.core.accessor.ConfigAccessor", return_value=MagicMock()),
        ):
            with pytest.raises(FileNotFoundError):
                import main  # noqa: F811

        # main should NOT be in sys.modules after a failed import
        assert "main" not in sys.modules, "main must not remain in sys.modules after failed import"

        # Second: simulate a successful import
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

            # Verify the import succeeded and app was created
            assert hasattr(main, "app"), "main.app must exist after successful import"
            assert main.app is mock_app, "main.app must be the return value of create_app()"