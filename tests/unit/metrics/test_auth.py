#!/usr/bin/env python3

"""Tests for metrics authentication module — UT-MA01 through UT-MA14.

Verifies ``MetricsAuthError``, ``validate_metrics_access``, and
``validate_metrics_token`` from ``src.metrics.auth``, plus module
purity (no FastAPI / HTTPException imports).
"""

import re
from unittest.mock import MagicMock

import pytest

from src.config.schemas import MetricsConfig
from src.metrics.auth import (
    MetricsAuthError,
    validate_metrics_access,
    validate_metrics_token,
)

# ---------------------------------------------------------------------------
# TestMetricsAuthError — UT-MA01, UT-MA02
# ---------------------------------------------------------------------------


class TestMetricsAuthError:
    """Tests for the MetricsAuthError domain exception."""

    def test_ma01_attributes(self) -> None:
        """UT-MA01: MetricsAuthError stores status_code and detail correctly."""
        e = MetricsAuthError(401, "Missing or invalid Authorization header")

        assert e.status_code == 401
        assert e.detail == "Missing or invalid Authorization header"

    def test_ma02_is_exception_subclass(self) -> None:
        """UT-MA02: MetricsAuthError is an instance of Exception."""
        e = MetricsAuthError(403, "Invalid metrics access token")

        assert isinstance(e, Exception)


# ---------------------------------------------------------------------------
# TestValidateMetricsAccess — UT-MA04, UT-MA05, UT-MA06, UT-MA07
# ---------------------------------------------------------------------------


class TestValidateMetricsAccess:
    """Tests for validate_metrics_access(accessor)."""

    def _make_accessor(self, enabled: bool, access_token: str) -> MagicMock:
        """Create a mock ConfigAccessor returning a MetricsConfig."""
        accessor = MagicMock()
        accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=enabled, access_token=access_token
        )
        return accessor

    def test_ma04_enabled_with_token_returns_token(self) -> None:
        """UT-MA04: metrics_config.enabled=True, access_token="my_token" → returns "my_token"."""
        accessor = self._make_accessor(enabled=True, access_token="my_token")

        result = validate_metrics_access(accessor)

        assert result == "my_token"

    def test_ma05_disabled_raises_404(self) -> None:
        """UT-MA05: metrics_config.enabled=False → raises MetricsAuthError(404, "Metrics endpoint is disabled")."""
        accessor = self._make_accessor(enabled=False, access_token="some_token")

        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_access(accessor)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Metrics endpoint is disabled"

    def test_ma06_enabled_empty_token_raises_404(self) -> None:
        """UT-MA06: metrics_config.enabled=True, access_token="" → raises MetricsAuthError(404, "Metrics endpoint is disabled")."""
        accessor = self._make_accessor(enabled=True, access_token="")

        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_access(accessor)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Metrics endpoint is disabled"

    def test_ma07_enabled_whitespace_token_raises_404(self) -> None:
        """UT-MA07: metrics_config.enabled=True, access_token="  " → raises MetricsAuthError(404, "Metrics endpoint is disabled")."""
        accessor = self._make_accessor(enabled=True, access_token="  ")

        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_access(accessor)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Metrics endpoint is disabled"


# ---------------------------------------------------------------------------
# TestValidateMetricsToken — UT-MA08, UT-MA09, UT-MA10, UT-MA11, UT-MA12
# ---------------------------------------------------------------------------


class TestValidateMetricsToken:
    """Tests for validate_metrics_token(raw_token, expected)."""

    def test_ma08_none_token_raises_401(self) -> None:
        """UT-MA08: raw_token=None → raises MetricsAuthError(401, "Missing or invalid Authorization header")."""
        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_token(None, "expected_token")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing or invalid Authorization header"

    def test_ma09_empty_token_raises_401(self) -> None:
        """UT-MA09: raw_token="" → raises MetricsAuthError(401, "Missing or invalid Authorization header")."""
        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_token("", "expected_token")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing or invalid Authorization header"

    def test_ma10_wrong_token_raises_403(self) -> None:
        """UT-MA10: raw_token="wrong_token", expected="correct_token" → raises MetricsAuthError(403, "Invalid metrics access token")."""
        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_token("wrong_token", "correct_token")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Invalid metrics access token"

    def test_ma11_matching_token_no_exception(self) -> None:
        """UT-MA11: raw_token="correct_token", expected="correct_token" → no exception, returns None."""
        result = validate_metrics_token("correct_token", "correct_token")

        assert result is None

    def test_ma12_bearer_prefix_token_raises_403(self) -> None:
        """UT-MA12: raw_token="Bearer correct_token", expected="correct_token" → raises MetricsAuthError(403) because validate_metrics_token receives a pre-extracted token."""
        with pytest.raises(MetricsAuthError) as exc_info:
            validate_metrics_token("Bearer correct_token", "correct_token")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Invalid metrics access token"


# ---------------------------------------------------------------------------
# TestAuthModulePurity — UT-MA13, UT-MA14
# ---------------------------------------------------------------------------


class TestAuthModulePurity:
    """Tests that src/metrics/auth.py has no web-framework dependencies."""

    def test_ma13_no_fastapi_import(self) -> None:
        """UT-MA13: Module does not import fastapi — verify by reading file."""
        import pathlib

        source = pathlib.Path("src/metrics/auth.py").read_text()
        matches = re.findall(r"from fastapi|import fastapi", source)

        assert matches == []

    def test_ma14_no_httpexception_import(self) -> None:
        """UT-MA14: Module does not import HTTPException — verify by reading file."""
        import pathlib

        source = pathlib.Path("src/metrics/auth.py").read_text()
        # Check for import statements only, not docstring mentions.
        # The module docstring explicitly declares "no dependencies on … HTTPException",
        # so the bare string appears in documentation — that is intentional.
        matches = re.findall(
            r"from\s+\w.*import\s+.*HTTPException|import\s+.*HTTPException", source
        )

        assert matches == []
