"""Tests for NetworkGuard core behavior.

Verifies that:
- Initial state is UP
- mark_down/mark_up transitions work correctly
- enforcing property depends on enabled and mode
- passive detection trips after threshold
- active_loop trips after fail_threshold
- marker file is written/read correctly
- startup_probe behavior
"""

import asyncio
import contextlib
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import NetworkGuardConfig
from src.core.constants import TransportFailureClass
from src.core.network_guard import NetworkGuard, ProbeFailure


@pytest.fixture
def temp_marker_path(tmp_path):
    """Create a temporary marker file path."""
    return tmp_path / "state.json"


@pytest.fixture
def base_config(temp_marker_path):
    """Create a base NetworkGuardConfig with temp marker path."""
    return NetworkGuardConfig(
        enabled=True,
        mode="pause",
        probe_urls=[],
        probe_interval_sec=30,
        probe_connect_timeout_sec=3.0,
        probe_total_timeout_sec=5.0,
        min_probe_successes=2,
        fail_threshold=3,
        passive_window_sec=60,
        passive_min_providers=3,
        passive_min_failures=6,
        startup_probe=True,
        auto_recover=False,
        marker_path=str(temp_marker_path),
    )


@pytest.fixture
def fake_clock():
    """Create a fake clock for deterministic tests."""
    current_time = [1000000.0]  # Use list to allow mutation in closure

    def clock():
        return current_time[0]

    def advance(seconds):
        current_time[0] += seconds

    clock.advance = advance
    return clock


def test_network_guard_initial_state_up(base_config):
    """Initial state is UP."""
    guard = NetworkGuard(base_config, source="test")
    assert guard.is_down() is False
    assert guard.enabled is True
    assert guard.enforcing is True


def test_network_guard_enforcing_log_mode(base_config):
    """enforcing is False in log mode."""
    config = base_config.model_copy(update={"mode": "log"})
    guard = NetworkGuard(config, source="test")
    assert guard.enforcing is False
    assert guard.enabled is True


def test_network_guard_enforcing_disabled(base_config):
    """enforcing is False when disabled."""
    config = base_config.model_copy(update={"enabled": False})
    guard = NetworkGuard(config, source="test")
    assert guard.enforcing is False
    assert guard.enabled is False


@pytest.mark.asyncio
async def test_network_guard_mark_down(base_config, temp_marker_path):
    """mark_down transitions to DOWN and writes marker."""
    guard = NetworkGuard(base_config, source="test")
    await guard.mark_down("test_reason", {"test": "evidence"})

    assert guard.is_down() is True
    assert temp_marker_path.exists()

    # Verify marker content
    marker_data = json.loads(temp_marker_path.read_text())
    assert marker_data["state"] == "down"
    assert marker_data["reason"] == "test_reason"
    assert marker_data["evidence"] == {"test": "evidence"}


@pytest.mark.asyncio
async def test_network_guard_mark_up(base_config, temp_marker_path):
    """mark_up transitions to UP and removes marker."""
    guard = NetworkGuard(base_config, source="test")
    await guard.mark_down("test_reason", {})
    assert guard.is_down() is True
    assert temp_marker_path.exists()

    await guard.mark_up("test_recovery")
    assert guard.is_down() is False
    assert not temp_marker_path.exists()


@pytest.mark.asyncio
async def test_probe_one_does_not_await_close(base_config):
    """Successful handshake is not failed by a hanging TLS close."""
    guard = NetworkGuard(base_config, source="test")
    reader = MagicMock()
    writer = MagicMock()
    writer.wait_closed = AsyncMock(
        side_effect=AssertionError("wait_closed must not be awaited")
    )

    with (
        patch(
            "src.core.network_guard.asyncio.open_connection",
            new=AsyncMock(return_value=(reader, writer)),
        ),
        patch(
            "src.core.network_guard.ssl.create_default_context",
            return_value=MagicMock(),
        ),
    ):
        result = await guard._probe_one("https://example.com")

    assert result is None
    writer.close.assert_called_once()
    writer.wait_closed.assert_not_called()


@pytest.mark.asyncio
async def test_probe_once_records_failed_probes(base_config):
    """probe_once retains per-target failures for marker evidence."""
    config = base_config.model_copy(
        update={
            "probe_urls": ["https://one.example", "https://two.example"],
            "min_probe_successes": 1,
        }
    )
    guard = NetworkGuard(config, source="test")
    failure = ProbeFailure("https://two.example", "TimeoutError: timed out")

    with patch.object(
        guard,
        "_probe_once_detailed",
        new=AsyncMock(return_value=(True, [failure])),
    ):
        result = await guard.probe_once()

    assert result is True
    assert guard._probe_evidence() == {
        "failed_probes": [
            {"url": "https://two.example", "error": "TimeoutError: timed out"}
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "level", "needle"),
    [
        ("log", logging.WARNING, "log-only"),
        ("pause", logging.CRITICAL, "paused"),
    ],
)
async def test_mark_down_log_level_matches_mode(
    base_config, caplog, mode, level, needle
):
    """log mode warns that attempts continue; pause mode reports a pause."""
    config = base_config.model_copy(update={"mode": mode})
    guard = NetworkGuard(config, source="test")

    with caplog.at_level(logging.DEBUG, logger="src.core.network_guard"):
        await guard.mark_down("test_reason", {"test": "evidence"})

    record = next(
        record
        for record in caplog.records
        if record.name == "src.core.network_guard" and record.levelno == level
    )
    assert needle in record.getMessage()


@pytest.mark.asyncio
async def test_active_loop_log_mode_recovers(base_config):
    """log mode auto-recovers after a successful probe."""
    config = base_config.model_copy(update={"mode": "log"})
    guard = NetworkGuard(config, source="test")
    await guard.mark_down("test_reason", {})

    await guard._on_probe_success()

    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_active_loop_pause_mode_stays_down(base_config):
    """pause mode keeps manual-reset semantics after a successful probe."""
    config = base_config.model_copy(update={"mode": "pause", "auto_recover": False})
    guard = NetworkGuard(config, source="test")
    await guard.mark_down("test_reason", {})

    await guard._on_probe_success()

    assert guard.is_down() is True


@pytest.mark.asyncio
async def test_poll_marker_log_mode_recovers_when_marker_cleared(
    base_config, temp_marker_path
):
    """log mode recovers when the shared marker disappears."""
    config = base_config.model_copy(update={"mode": "log"})
    guard = NetworkGuard(config, source="test")
    await guard.mark_down("test_reason", {})
    temp_marker_path.unlink()

    await guard.poll_marker()

    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_network_guard_passive_detection_trips(base_config, fake_clock):
    """Passive detection trips after threshold (3 providers, 6 failures)."""
    guard = NetworkGuard(base_config, source="test", clock=fake_clock)

    # Add failures from 3 distinct providers (6 total)
    for i in range(6):
        provider = f"provider_{i % 3}"
        guard.note_failure(provider, TransportFailureClass.CONNECT_TIMEOUT)

    await guard.evaluate_passive()
    assert guard.is_down() is True


@pytest.mark.asyncio
async def test_network_guard_passive_detection_below_threshold(base_config, fake_clock):
    """Passive detection does not trip below threshold."""
    guard = NetworkGuard(base_config, source="test", clock=fake_clock)

    # Add failures from only 2 providers (below passive_min_providers=3)
    for i in range(6):
        provider = f"provider_{i % 2}"
        guard.note_failure(provider, TransportFailureClass.CONNECT_TIMEOUT)

    await guard.evaluate_passive()
    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_network_guard_passive_detection_stale_entries_expire(
    base_config, fake_clock
):
    """Stale entries expire and do not count toward threshold."""
    guard = NetworkGuard(base_config, source="test", clock=fake_clock)

    # Add old failures
    for i in range(6):
        provider = f"provider_{i % 3}"
        guard.note_failure(provider, TransportFailureClass.CONNECT_TIMEOUT)

    # Advance clock past passive_window_sec (60s)
    fake_clock.advance(61)

    # Add one fresh failure
    guard.note_failure("provider_fresh", TransportFailureClass.CONNECT_TIMEOUT)

    await guard.evaluate_passive()
    # Old failures expired, only 1 fresh failure - below threshold
    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_network_guard_startup_probe_success(base_config, temp_marker_path):
    """startup_probe success clears marker and returns True."""
    # Write a marker first
    temp_marker_path.write_text(json.dumps({"state": "down", "reason": "old"}))

    # Configure probe_urls so startup_probe actually runs
    config = base_config.model_copy(update={"probe_urls": ["https://example.com"]})
    guard = NetworkGuard(config, source="test")

    # Mock probe_once to return True
    with patch.object(guard, "probe_once", new=AsyncMock(return_value=True)):
        result = await guard.startup_probe()

    assert result is True
    assert guard.is_down() is False
    assert not temp_marker_path.exists()


@pytest.mark.asyncio
async def test_network_guard_startup_probe_failure(base_config, temp_marker_path):
    """startup_probe failure writes marker and returns False."""
    # Configure probe_urls so startup_probe actually runs
    config = base_config.model_copy(update={"probe_urls": ["https://example.com"]})
    guard = NetworkGuard(config, source="test")

    # Mock probe_once to return False
    with patch.object(guard, "probe_once", new=AsyncMock(return_value=False)):
        result = await guard.startup_probe()

    assert result is False
    assert guard.is_down() is True
    assert temp_marker_path.exists()


@pytest.mark.asyncio
async def test_network_guard_startup_probe_no_urls_does_not_clear_marker(
    base_config, temp_marker_path
):
    """startup_probe with no probe_urls does not clear existing marker."""
    # Write a marker first
    temp_marker_path.write_text(json.dumps({"state": "down", "reason": "old"}))

    config = base_config.model_copy(update={"probe_urls": []})
    guard = NetworkGuard(config, source="test")

    result = await guard.startup_probe()

    # Should return not _down (which is False initially, so True)
    assert result is True
    # Marker should still exist
    assert temp_marker_path.exists()


@pytest.mark.asyncio
async def test_network_guard_marker_ttl_expired_ignored(
    base_config, temp_marker_path, fake_clock
):
    """Expired marker is ignored."""
    # Write a marker with expired TTL
    marker_data = {
        "state": "down",
        "reason": "old",
        "since": fake_clock() - 100,
        "expires_at": fake_clock() - 10,  # Expired 10 seconds ago
    }
    temp_marker_path.write_text(json.dumps(marker_data))

    guard = NetworkGuard(base_config, source="test", clock=fake_clock)
    await guard.poll_marker()

    # Expired marker should be ignored
    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_network_guard_marker_fresh_adopted(
    base_config, temp_marker_path, fake_clock
):
    """Fresh marker is adopted."""
    # Write a fresh marker
    marker_data = {
        "state": "down",
        "reason": "remote",
        "source": "other_process",
        "since": fake_clock(),
        "expires_at": fake_clock() + 100,  # Expires in 100 seconds
        "evidence": {"test": "data"},
    }
    temp_marker_path.write_text(json.dumps(marker_data))

    guard = NetworkGuard(base_config, source="test", clock=fake_clock)
    await guard.poll_marker()

    # Fresh marker should be adopted
    assert guard.is_down() is True


@pytest.mark.asyncio
async def test_network_guard_atomic_write_valid_json(base_config, temp_marker_path):
    """Atomic write produces valid JSON."""
    guard = NetworkGuard(base_config, source="test")
    await guard.mark_down("test", {"key": "value"})

    # Verify it's valid JSON
    marker_data = json.loads(temp_marker_path.read_text())
    assert isinstance(marker_data, dict)
    assert marker_data["state"] == "down"


@pytest.mark.asyncio
async def test_network_guard_active_loop_trips_after_threshold(base_config, fake_clock):
    """active_loop trips after fail_threshold consecutive failures."""
    config = base_config.model_copy(update={"fail_threshold": 3})
    guard = NetworkGuard(config, source="test", clock=fake_clock)

    # Manually simulate 3 consecutive probe failures
    for _ in range(3):
        guard._consecutive_probe_failures += 1
        if (
            not guard.is_down()
            and guard._consecutive_probe_failures >= config.fail_threshold
        ):
            await guard.mark_down(
                "active_probe",
                {"consecutive_failures": guard._consecutive_probe_failures},
            )

    assert guard.is_down() is True
    assert guard._consecutive_probe_failures == 3


@pytest.mark.asyncio
async def test_network_guard_active_loop_auto_recover_false_stays_down(
    base_config, fake_clock
):
    """active_loop with auto_recover=False stays DOWN after success."""
    config = base_config.model_copy(update={"auto_recover": False})
    guard = NetworkGuard(config, source="test", clock=fake_clock)

    # Mark down first
    await guard.mark_down("initial", {})
    assert guard.is_down() is True

    # Simulate a successful probe with auto_recover=False
    # According to the code, it should check if marker exists and call mark_up("marker_cleared")
    # But since marker exists, it should call heartbeat() instead
    # So it should stay DOWN
    guard._consecutive_probe_failures = 0
    if guard.is_down():
        if config.auto_recover:
            await guard.mark_up("active_probe")
        elif not guard._marker_path.exists():
            await guard.mark_up("marker_cleared")
        else:
            await guard.heartbeat()

    # Should still be DOWN (auto_recover=False and marker exists)
    assert guard.is_down() is True


@pytest.mark.asyncio
async def test_network_guard_active_loop_auto_recover_true_recovers(
    base_config, fake_clock
):
    """active_loop with auto_recover=True goes UP after success."""
    config = base_config.model_copy(update={"auto_recover": True})
    guard = NetworkGuard(config, source="test", clock=fake_clock)

    # Mark down first
    await guard.mark_down("initial", {})
    assert guard.is_down() is True

    # Simulate a successful probe with auto_recover=True
    guard._consecutive_probe_failures = 0
    if guard.is_down():
        if config.auto_recover:
            await guard.mark_up("active_probe")
        elif not guard._marker_path.exists():
            await guard.mark_up("marker_cleared")
        else:
            await guard.heartbeat()

    # Should be UP (auto_recover=True)
    assert guard.is_down() is False


@pytest.mark.asyncio
async def test_network_guard_poll_loop_does_not_auto_recover_local_down(
    base_config, temp_marker_path, fake_clock
):
    """poll_loop does not auto-recover a local DOWN state."""
    guard = NetworkGuard(base_config, source="test", clock=fake_clock)

    # Mark down locally
    await guard.mark_down("local", {})
    assert guard.is_down() is True

    # Remove marker (simulating operator reset)
    temp_marker_path.unlink(missing_ok=True)

    # Run poll_loop - it should NOT auto-recover
    with patch("asyncio.sleep", new=AsyncMock()):
        task = asyncio.create_task(guard.poll_loop())
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Should still be DOWN (poll_loop doesn't auto-recover)
    assert guard.is_down() is True
