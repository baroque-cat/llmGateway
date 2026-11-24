"""Integration tests for NetworkGuard marker sharing between processes.

Verifies that:
- Two guards sharing the same marker_path can coordinate state
- guard1.mark_down() is visible to guard2 via poll_marker()
- guard2.mark_up() removes the marker
- Expired markers are ignored
"""

import json
from pathlib import Path

import pytest

from src.config.schemas import NetworkGuardConfig
from src.core.network_guard import NetworkGuard


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
    current_time = [1000000.0]

    def clock():
        return current_time[0]

    def advance(seconds):
        current_time[0] += seconds

    clock.advance = advance
    return clock


@pytest.mark.asyncio
async def test_two_guards_share_marker_down(base_config, fake_clock):
    """guard1.mark_down() is visible to guard2 via poll_marker()."""
    guard1 = NetworkGuard(base_config, source="gateway", clock=fake_clock)
    guard2 = NetworkGuard(base_config, source="keeper", clock=fake_clock)

    # guard1 marks down
    await guard1.mark_down("test_reason", {"test": "evidence"})
    assert guard1.is_down() is True

    # guard2 should see the marker
    await guard2.poll_marker()
    assert guard2.is_down() is True

    # Verify the marker file exists
    marker_path = Path(base_config.marker_path)
    assert marker_path.exists()

    # Verify marker content
    marker_data = json.loads(marker_path.read_text())
    assert marker_data["state"] == "down"
    assert marker_data["reason"] == "test_reason"
    assert marker_data["evidence"] == {"test": "evidence"}


@pytest.mark.asyncio
async def test_guard_mark_up_removes_marker(base_config, fake_clock):
    """guard2.mark_up() removes the marker."""
    guard1 = NetworkGuard(base_config, source="gateway", clock=fake_clock)
    guard2 = NetworkGuard(base_config, source="keeper", clock=fake_clock)

    # guard1 marks down
    await guard1.mark_down("test_reason", {})
    assert guard1.is_down() is True

    # guard2 adopts the marker
    await guard2.poll_marker()
    assert guard2.is_down() is True

    # guard2 marks up
    await guard2.mark_up("reset")
    assert guard2.is_down() is False

    # Marker should be removed
    marker_path = Path(base_config.marker_path)
    assert not marker_path.exists()

    # A third guard with startup_probe=False should see no marker
    config_no_probe = base_config.model_copy(update={"startup_probe": False})
    guard3 = NetworkGuard(config_no_probe, source="test", clock=fake_clock)
    result = await guard3.startup_probe()
    assert result is True  # not _down (which is False initially)
    assert guard3.is_down() is False


@pytest.mark.asyncio
async def test_expired_marker_ignored(base_config, fake_clock):
    """Marker with expired expires_at is ignored by poll_marker."""
    guard1 = NetworkGuard(base_config, source="gateway", clock=fake_clock)
    guard2 = NetworkGuard(base_config, source="keeper", clock=fake_clock)

    # guard1 marks down
    await guard1.mark_down("test_reason", {})
    assert guard1.is_down() is True

    # Advance clock past TTL (max(2*probe_interval_sec, 60) = 60s)
    fake_clock.advance(61)

    # guard2 should ignore the expired marker
    await guard2.poll_marker()
    assert guard2.is_down() is False


@pytest.mark.asyncio
async def test_fresh_marker_adopted(base_config, fake_clock):
    """Fresh marker is adopted by poll_marker."""
    guard1 = NetworkGuard(base_config, source="gateway", clock=fake_clock)
    guard2 = NetworkGuard(base_config, source="keeper", clock=fake_clock)

    # guard1 marks down
    await guard1.mark_down("test_reason", {"providers": ["p1", "p2"]})
    assert guard1.is_down() is True

    # guard2 should adopt the fresh marker
    await guard2.poll_marker()
    assert guard2.is_down() is True

    # Verify the evidence was preserved
    assert "providers" in guard2._evidence


@pytest.mark.asyncio
async def test_marker_atomic_write(base_config, fake_clock):
    """Marker is written atomically (tmp + rename)."""
    guard = NetworkGuard(base_config, source="test", clock=fake_clock)

    # Mark down multiple times to trigger multiple writes
    # Advance clock between calls to allow heartbeat to write
    for i in range(5):
        await guard.mark_down(f"reason_{i}", {"iteration": i})
        # Advance clock past probe_interval_sec (30s) to allow heartbeat
        fake_clock.advance(31)

    # Verify the final marker is valid JSON
    marker_path = Path(base_config.marker_path)
    assert marker_path.exists()
    marker_data = json.loads(marker_path.read_text())
    assert marker_data["state"] == "down"
    assert marker_data["reason"] == "reason_4"
    assert marker_data["evidence"] == {"iteration": 4}

    # Verify no tmp files are left behind
    parent_dir = marker_path.parent
    tmp_files = list(parent_dir.glob("*.tmp"))
    assert len(tmp_files) == 0
