#!/usr/bin/env python3

"""Tests for CheckResult and RequestDetails models from src.core.models."""

import pytest

from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails

# ---------------------------------------------------------------------------
# CheckResult.success()
# ---------------------------------------------------------------------------


def test_check_result_success_creates_ok_result() -> None:
    """CheckResult.success() creates a result with available=True."""
    result = CheckResult.success()
    assert result.available is True


def test_check_result_success_default_values() -> None:
    """CheckResult.success() defaults: message, response_time=0.0, status_code=200."""
    result = CheckResult.success()
    assert result.message == "Key is valid and operational."
    assert result.response_time == 0.0
    assert result.status_code == 200


def test_check_result_success_custom_values() -> None:
    """CheckResult.success() accepts custom message, response_time, status_code."""
    result = CheckResult.success(message="All good", response_time=1.5, status_code=204)
    assert result.available is True
    assert result.message == "All good"
    assert result.response_time == 1.5
    assert result.status_code == 204


# ---------------------------------------------------------------------------
# CheckResult.fail()
# ---------------------------------------------------------------------------


def test_check_result_fail_default_message() -> None:
    """CheckResult.fail(ErrorReason.RATE_LIMITED) → message == 'Rate limited'."""
    result = CheckResult.fail(ErrorReason.RATE_LIMITED)
    assert result.message == "Rate limited"


def test_check_result_fail_custom_message() -> None:
    """CheckResult.fail(ErrorReason.INVALID_KEY, 'custom msg') → message == 'custom msg'."""
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "custom msg")
    assert result.message == "custom msg"


def test_check_result_fail_available_is_false() -> None:
    """CheckResult.fail() always sets available=False."""
    result = CheckResult.fail(ErrorReason.RATE_LIMITED)
    assert result.available is False


# ---------------------------------------------------------------------------
# CheckResult.ok property
# ---------------------------------------------------------------------------


def test_check_result_ok_when_available_true() -> None:
    """ok property returns True when available is True."""
    result = CheckResult.success()
    assert result.ok is True


def test_check_result_ok_when_available_false() -> None:
    """ok property returns False when available is False."""
    result = CheckResult.fail(ErrorReason.RATE_LIMITED)
    assert result.ok is False


# ---------------------------------------------------------------------------
# CheckResult.to_dict()
# ---------------------------------------------------------------------------


def test_check_result_to_dict_success() -> None:
    """to_dict() serializes a successful CheckResult correctly."""
    result = CheckResult.success(message="OK", response_time=0.3, status_code=200)
    d = result.to_dict()
    assert d["available"] is True
    assert d["error_reason"] == "unknown"
    assert d["message"] == "OK"
    assert d["response_time"] == 0.3
    assert d["status_code"] == 200


def test_check_result_to_dict_fail() -> None:
    """to_dict() serializes a failed CheckResult correctly."""
    result = CheckResult.fail(
        ErrorReason.INVALID_KEY, "bad key", response_time=1.0, status_code=401
    )
    d = result.to_dict()
    assert d["available"] is False
    assert d["error_reason"] == "invalid_key"
    assert d["message"] == "bad key"
    assert d["response_time"] == 1.0
    assert d["status_code"] == 401


# ---------------------------------------------------------------------------
# RequestDetails
# ---------------------------------------------------------------------------


def test_request_details_creation() -> None:
    """RequestDetails can be created with model_name."""
    details = RequestDetails(model_name="gpt-4")
    assert details.model_name == "gpt-4"


def test_request_details_frozen() -> None:
    """RequestDetails is a frozen dataclass — modifying a field raises FrozenInstanceError."""
    details = RequestDetails(model_name="gpt-4")
    with pytest.raises(AttributeError):
        details.model_name = "gpt-3.5"
