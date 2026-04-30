#!/usr/bin/env python3

"""Tests for policy_utils purity — compute_next_check_time accepts keyword-only
params, has no config/db imports, and should_vacuum pure function logic."""

import ast
import importlib
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from src.core.constants import ErrorReason
from src.core.models import DatabaseTableHealth
from src.core.policy_utils import compute_next_check_time, should_vacuum

# ---------------------------------------------------------------------------
# 2.1-a: Keyword-only parameter acceptance
# ---------------------------------------------------------------------------


def test_compute_next_check_time_accepts_keyword_args() -> None:
    """Function accepts 7 keyword-only int/float parameters."""
    result = compute_next_check_time(
        ErrorReason.NO_QUOTA,
        on_no_quota_hr=1,
        on_rate_limit_hr=2,
        on_invalid_key_days=3,
        on_no_access_days=4,
        on_server_error_min=5,
        on_overload_min=6,
        on_other_error_hr=7,
    )
    # Just verify it returns a datetime — the specific mapping is tested below.
    assert isinstance(result, datetime)


def test_compute_next_check_time_missing_param_raises_type_error() -> None:
    """Calling without all 7 kwargs raises TypeError."""
    with pytest.raises(TypeError):
        compute_next_check_time(
            ErrorReason.NO_QUOTA,
            on_no_quota_hr=1,
            # Missing the other 6 kwargs
        )


# ---------------------------------------------------------------------------
# 2.1-b: ErrorReason → interval mapping
# ---------------------------------------------------------------------------


# Helper: compute delta from "now" and check it matches the expected timedelta.
def _delta_hours(result: datetime, expected_hr: int) -> bool:
    """Check that result is approximately now + expected_hr hours."""
    now = datetime.now(UTC)
    diff = result - now
    expected = timedelta(hours=expected_hr)
    # Allow 2-second tolerance for test execution time
    return abs(diff - expected) < timedelta(seconds=2)


def _delta_days(result: datetime, expected_days: int) -> bool:
    now = datetime.now(UTC)
    diff = result - now
    expected = timedelta(days=expected_days)
    return abs(diff - expected) < timedelta(seconds=2)


def _delta_minutes(result: datetime, expected_min: int) -> bool:
    now = datetime.now(UTC)
    diff = result - now
    expected = timedelta(minutes=expected_min)
    return abs(diff - expected) < timedelta(seconds=2)


# Default kwargs used across mapping tests
_KWARGS = {
    "on_no_quota_hr": 10,
    "on_rate_limit_hr": 5,
    "on_invalid_key_days": 7,
    "on_no_access_days": 30,
    "on_server_error_min": 15,
    "on_overload_min": 3,
    "on_other_error_hr": 2,
}


def test_compute_next_check_time_no_quota_uses_on_no_quota_hr() -> None:
    result = compute_next_check_time(ErrorReason.NO_QUOTA, **_KWARGS)
    assert _delta_hours(result, _KWARGS["on_no_quota_hr"])


def test_compute_next_check_time_rate_limited_uses_on_rate_limit_hr() -> None:
    result = compute_next_check_time(ErrorReason.RATE_LIMITED, **_KWARGS)
    assert _delta_hours(result, _KWARGS["on_rate_limit_hr"])


def test_compute_next_check_time_invalid_key_uses_on_invalid_key_days() -> None:
    result = compute_next_check_time(ErrorReason.INVALID_KEY, **_KWARGS)
    assert _delta_days(result, _KWARGS["on_invalid_key_days"])


def test_compute_next_check_time_server_error_uses_on_server_error_min() -> None:
    result = compute_next_check_time(ErrorReason.SERVER_ERROR, **_KWARGS)
    assert _delta_minutes(result, _KWARGS["on_server_error_min"])


def test_compute_next_check_time_overloaded_uses_on_overload_min() -> None:
    result = compute_next_check_time(ErrorReason.OVERLOADED, **_KWARGS)
    assert _delta_minutes(result, _KWARGS["on_overload_min"])


def test_compute_next_check_time_unknown_uses_on_other_error_hr() -> None:
    result = compute_next_check_time(ErrorReason.UNKNOWN, **_KWARGS)
    assert _delta_hours(result, _KWARGS["on_other_error_hr"])


def test_compute_next_check_time_no_access_uses_on_no_access_days() -> None:
    result = compute_next_check_time(ErrorReason.NO_ACCESS, **_KWARGS)
    assert _delta_days(result, _KWARGS["on_no_access_days"])


def test_compute_next_check_time_timeout_uses_on_server_error_min() -> None:
    result = compute_next_check_time(ErrorReason.TIMEOUT, **_KWARGS)
    assert _delta_minutes(result, _KWARGS["on_server_error_min"])


def test_compute_next_check_time_network_error_uses_on_server_error_min() -> None:
    result = compute_next_check_time(ErrorReason.NETWORK_ERROR, **_KWARGS)
    assert _delta_minutes(result, _KWARGS["on_server_error_min"])


def test_compute_next_check_time_bad_request_uses_on_other_error_hr() -> None:
    result = compute_next_check_time(ErrorReason.BAD_REQUEST, **_KWARGS)
    assert _delta_hours(result, _KWARGS["on_other_error_hr"])


# ---------------------------------------------------------------------------
# 2.1-c: Purity — no config/db imports
# ---------------------------------------------------------------------------


def test_policy_utils_no_config_imports() -> None:
    """policy_utils.py does not import from src.config or src.db."""
    source_path = pathlib.Path(importlib.util.find_spec("src.core.policy_utils").origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = getattr(node, "module", "") or ""
            if module_name.startswith("src.config") or module_name.startswith("src.db"):
                pytest.fail(
                    f"policy_utils.py imports from config/db layer: {module_name}"
                )


# ---------------------------------------------------------------------------
# M12–M17: should_vacuum pure function tests
# ---------------------------------------------------------------------------


def test_should_vacuum_high_ratio_triggers() -> None:
    """should_vacuum returns True when dead_tuple_ratio exceeds threshold and n_dead_tup > 100."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=1000,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.5,
    )
    assert should_vacuum(health, threshold=0.3) is True


def test_should_vacuum_low_ratio_does_not_trigger() -> None:
    """should_vacuum returns False when dead_tuple_ratio is below threshold."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=4500,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.1,
    )
    assert should_vacuum(health, threshold=0.3) is False


def test_should_vacuum_dead_tuples_below_100_does_not_trigger() -> None:
    """should_vacuum returns False when n_dead_tup < 100 (absolute guard)."""
    health = DatabaseTableHealth(
        table_name="public.proxies",
        n_dead_tup=50,
        n_live_tup=100,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.5,
    )
    assert should_vacuum(health, threshold=0.3) is False


def test_should_vacuum_exact_threshold_does_not_trigger() -> None:
    """should_vacuum returns False when ratio equals threshold (strictly > required)."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=500,
        n_live_tup=1167,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.3,
    )
    assert should_vacuum(health, threshold=0.3) is False


def test_should_vacuum_zero_dead_tuples() -> None:
    """should_vacuum returns False when n_dead_tup=0 and ratio=0.0."""
    health = DatabaseTableHealth(
        table_name="public.api_keys",
        n_dead_tup=0,
        n_live_tup=10000,
        last_vacuum=None,
        last_analyze=None,
        dead_tuple_ratio=0.0,
    )
    assert should_vacuum(health, threshold=0.3) is False


def test_should_vacuum_purity_no_config_db_imports() -> None:
    """policy_utils.py does NOT import src.config or src.db (AST check)."""
    source_path = pathlib.Path(importlib.util.find_spec("src.core.policy_utils").origin)
    source_text = source_path.read_text()
    tree = ast.parse(source_text)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = getattr(node, "module", "") or ""
            if module_name.startswith("src.config") or module_name.startswith("src.db"):
                pytest.fail(
                    f"policy_utils.py imports from config/db layer: {module_name}"
                )
