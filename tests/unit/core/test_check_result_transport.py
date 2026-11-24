#!/usr/bin/env python3

"""
Tests for CheckResult transport_class field — UT-CRT01 through UT-CRT05.

Verifies that:
  - CheckResult.fail() accepts and stores transport_class
  - CheckResult.to_dict() includes transport_class only when set
  - CheckResult.success() has transport_class=None
  - TransportFailureClass enum values are stable strings
"""

import pytest

from src.core.constants import ErrorReason, TransportFailureClass
from src.core.models import CheckResult

# ---------------------------------------------------------------------------
# UT-CRT01 — CheckResult.fail() accepts transport_class parameter
# ---------------------------------------------------------------------------


def test_fail_accepts_transport_class() -> None:
    """UT-CRT01: CheckResult.fail() stores transport_class when provided."""
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Connection timed out",
        transport_class=TransportFailureClass.CONNECT_TIMEOUT,
    )
    assert result.transport_class == TransportFailureClass.CONNECT_TIMEOUT
    assert result.transport_class.value == "connect_timeout"


def test_fail_without_transport_class_is_none() -> None:
    """UT-CRT01: CheckResult.fail() defaults transport_class to None."""
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Bad key")
    assert result.transport_class is None


# ---------------------------------------------------------------------------
# UT-CRT02 — CheckResult.to_dict() includes transport_class only when set
# ---------------------------------------------------------------------------


def test_to_dict_includes_transport_class_when_set() -> None:
    """UT-CRT02: to_dict() includes transport_class key when it is not None."""
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Read timeout",
        transport_class=TransportFailureClass.READ_TIMEOUT,
    )
    d = result.to_dict()
    assert "transport_class" in d
    assert d["transport_class"] == "read_timeout"


def test_to_dict_excludes_transport_class_when_none() -> None:
    """UT-CRT02: to_dict() omits transport_class key when it is None."""
    result = CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited")
    d = result.to_dict()
    assert "transport_class" not in d


# ---------------------------------------------------------------------------
# UT-CRT03 — CheckResult.success() has transport_class=None
# ---------------------------------------------------------------------------


def test_success_has_no_transport_class() -> None:
    """UT-CRT03: CheckResult.success() has transport_class=None."""
    result = CheckResult.success()
    assert result.transport_class is None
    d = result.to_dict()
    assert "transport_class" not in d


# ---------------------------------------------------------------------------
# UT-CRT04 — TransportFailureClass enum values are stable strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member,expected_value",
    [
        (TransportFailureClass.CONNECT_TIMEOUT, "connect_timeout"),
        (TransportFailureClass.CONNECT_ERROR, "connect_error"),
        (TransportFailureClass.POOL_TIMEOUT, "pool_timeout"),
        (TransportFailureClass.READ_TIMEOUT, "read_timeout"),
        (TransportFailureClass.STREAM_READ_TIMEOUT, "stream_read_timeout"),
        (TransportFailureClass.WRITE_TIMEOUT, "write_timeout"),
        (TransportFailureClass.REMOTE_PROTOCOL, "remote_protocol"),
        (TransportFailureClass.POOL_SATURATED, "pool_saturated"),
        (TransportFailureClass.REQUEST_ERROR, "request_error"),
    ],
)
def test_transport_failure_class_values(
    member: TransportFailureClass, expected_value: str
) -> None:
    """UT-CRT04: Each TransportFailureClass member has a stable string value."""
    assert member.value == expected_value


# ---------------------------------------------------------------------------
# UT-CRT05 — All transport classes can be used with fail()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transport_class",
    list(TransportFailureClass),
    ids=[tc.value for tc in TransportFailureClass],
)
def test_all_transport_classes_work_with_fail(
    transport_class: TransportFailureClass,
) -> None:
    """UT-CRT05: Every TransportFailureClass value can be passed to fail()."""
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Transport error",
        transport_class=transport_class,
    )
    assert result.transport_class == transport_class
    d = result.to_dict()
    assert d["transport_class"] == transport_class.value
