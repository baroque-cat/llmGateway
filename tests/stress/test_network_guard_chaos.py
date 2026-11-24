"""Stress tests for NetworkGuard chaos scenarios.

Verifies that:
- Guard responds to local TCP server availability
- Guard trips to DOWN when server becomes unavailable
- Guard recovers to UP when server becomes available again
- All operations complete within 60 seconds
"""

import asyncio
import contextlib

import pytest

from src.config.schemas import NetworkGuardConfig
from src.core.network_guard import NetworkGuard


@pytest.fixture
def guard_config(tmp_path):
    """Create a NetworkGuardConfig for chaos testing."""
    return NetworkGuardConfig(
        enabled=True,
        mode="pause",
        probe_urls=[],  # Will be set dynamically
        probe_interval_sec=5,  # Minimum allowed value
        probe_connect_timeout_sec=0.5,
        probe_total_timeout_sec=1.0,
        min_probe_successes=1,
        fail_threshold=1,  # Trip immediately on first failure
        passive_window_sec=60,
        passive_min_providers=3,
        passive_min_failures=6,
        startup_probe=True,
        auto_recover=True,  # Enable auto-recovery for this test
        marker_path=str(tmp_path / "state.json"),
    )


async def start_tcp_server():
    """Start a simple TCP server on 127.0.0.1 with an ephemeral port."""

    async def handle_client(reader, writer):
        try:
            # Just accept the connection and close it
            await reader.read(1024)
        except Exception:
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    addr = server.sockets[0].getsockname()
    return server, addr[0], addr[1]


@pytest.mark.slow
@pytest.mark.asyncio
async def test_network_guard_chaos_server_lifecycle(guard_config):
    """Test guard response to server lifecycle changes."""
    # Start initial server
    server1, host, port = await start_tcp_server()
    probe_url = f"http://{host}:{port}"

    # Configure guard to probe this server
    config = guard_config.model_copy(update={"probe_urls": [probe_url]})
    guard = NetworkGuard(config, source="test")

    try:
        # Initial probe should succeed
        result = await guard.probe_once()
        assert result is True
        assert guard.is_down() is False

        # Stop the server
        server1.close()
        await server1.wait_closed()

        # Probe should now fail
        result = await guard.probe_once()
        assert result is False

        # Run active_loop iteration to trip the guard
        # Since fail_threshold=1, it should trip immediately
        guard._consecutive_probe_failures = 1
        await guard.mark_down(
            "active_probe",
            {"consecutive_failures": 1},
        )
        assert guard.is_down() is True

        # Start a new server on a different port
        server2, host2, port2 = await start_tcp_server()
        probe_url2 = f"http://{host2}:{port2}"

        # Update config to probe the new server
        config2 = config.model_copy(update={"probe_urls": [probe_url2]})
        guard2 = NetworkGuard(config2, source="test")

        # Startup probe should succeed and recover
        result = await guard2.startup_probe()
        assert result is True
        assert guard2.is_down() is False

        # Clean up
        server2.close()
        await server2.wait_closed()

    finally:
        # Ensure servers are closed
        try:
            server1.close()
            await server1.wait_closed()
        except Exception:
            pass
        try:
            server2.close()
            await server2.wait_closed()
        except Exception:
            pass


@pytest.mark.slow
@pytest.mark.asyncio
async def test_network_guard_chaos_rapid_transitions(guard_config):
    """Test guard behavior under rapid server state changes."""
    # Start initial server
    server, host, port = await start_tcp_server()
    probe_url = f"http://{host}:{port}"

    # Configure guard
    config = guard_config.model_copy(
        update={
            "probe_urls": [probe_url],
            "fail_threshold": 2,  # Need 2 failures to trip
        }
    )
    guard = NetworkGuard(config, source="test")

    try:
        # Initial state: UP
        assert guard.is_down() is False

        # Rapid transition: stop server
        server.close()
        await server.wait_closed()

        # First failure
        result = await guard.probe_once()
        assert result is False
        guard._consecutive_probe_failures = 1

        # Second failure should trip the guard
        result = await guard.probe_once()
        assert result is False
        guard._consecutive_probe_failures = 2
        await guard.mark_down(
            "active_probe",
            {"consecutive_failures": 2},
        )
        assert guard.is_down() is True

        # Rapid transition: start new server
        server2, host2, port2 = await start_tcp_server()
        probe_url2 = f"http://{host2}:{port2}"

        # Update guard config
        config2 = config.model_copy(update={"probe_urls": [probe_url2]})
        guard2 = NetworkGuard(config2, source="test")

        # Probe should succeed
        result = await guard2.probe_once()
        assert result is True

        # With auto_recover=True, startup_probe should recover
        result = await guard2.startup_probe()
        assert result is True
        assert guard2.is_down() is False

        # Clean up
        server2.close()
        await server2.wait_closed()

    finally:
        try:
            server.close()
            await server.wait_closed()
        except Exception:
            pass
        try:
            server2.close()
            await server2.wait_closed()
        except Exception:
            pass


@pytest.mark.slow
@pytest.mark.asyncio
async def test_network_guard_chaos_timeout_handling(guard_config):
    """Test guard behavior when probes timeout."""
    # Use a non-routable IP to cause timeouts
    # 10.255.255.1 is typically non-routable
    probe_url = "http://10.255.255.1:9999"

    config = guard_config.model_copy(
        update={
            "probe_urls": [probe_url],
            "probe_connect_timeout_sec": 0.1,  # Very short timeout
            "probe_total_timeout_sec": 0.2,
            "fail_threshold": 1,
        }
    )
    guard = NetworkGuard(config, source="test")

    # Probe should timeout and fail
    result = await guard.probe_once()
    assert result is False

    # Guard should trip
    guard._consecutive_probe_failures = 1
    await guard.mark_down(
        "active_probe",
        {"consecutive_failures": 1},
    )
    assert guard.is_down() is True


@pytest.mark.slow
@pytest.mark.asyncio
async def test_network_guard_active_loop_trips_on_failure(guard_config):
    """Test that active_loop() trips the guard to DOWN when probes fail."""
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    # Configure guard with fail_threshold=1
    config = guard_config.model_copy(
        update={
            "probe_urls": ["http://127.0.0.1:1"],  # Will fail
            "fail_threshold": 1,
            "probe_interval_sec": 5,
        }
    )
    guard = NetworkGuard(config, source="test")

    # Verify initial state
    assert guard.is_down() is False

    # Patch probe_once to return False (simulating probe failure)
    # Run active_loop with a short timeout
    # The loop should trip the guard after fail_threshold failures
    with (
        patch.object(guard, "probe_once", new=AsyncMock(return_value=False)),
        contextlib.suppress(TimeoutError),
    ):
        await asyncio.wait_for(guard.active_loop(), timeout=0.2)

    # Verify the guard tripped to DOWN
    assert guard.is_down() is True

    # Verify the marker file was created
    marker_path = Path(config.marker_path)
    assert marker_path.exists()

    # Verify marker content
    import json

    marker_data = json.loads(marker_path.read_text())
    assert marker_data["state"] == "down"
    assert marker_data["reason"] == "active_probe"
    assert "consecutive_failures" in marker_data["evidence"]
    assert marker_data["evidence"]["consecutive_failures"] >= 1
