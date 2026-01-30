import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.config.schemas import HealthPolicyConfig
from src.services.probes.key_probe import KeyProbe

@pytest.mark.asyncio
async def test_network_error_uses_server_error_policy():
    """
    Verifies that ErrorReason.NETWORK_ERROR triggers the 'on_server_error_min' interval
    defined in the worker health policy.
    """
    # 1. Setup Dependencies
    mock_db = MagicMock()
    mock_http = MagicMock()
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10 # Required for Semaphore init

    # 2. Initialize KeyProbe
    # Correct order: accessor, db_manager, client_factory
    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    # 3. Define Policy
    # We set on_server_error_min to a distinct value (e.g., 42 minutes) to ensure
    # we are verifying the correct config mapping, not just a default.
    test_interval_min = 42
    policy = HealthPolicyConfig(on_server_error_min=test_interval_min)

    # 4. Create a specific failure result (NETWORK_ERROR)
    result = CheckResult.fail(ErrorReason.NETWORK_ERROR, "Simulated network failure")

    # 5. Execute Logic
    # We pass failing_since=None to bypass quarantine logic and hit the standard backoff logic
    now = datetime.now(timezone.utc)
    next_check = probe._calculate_next_check_time(policy, result, failing_since=None)

    # 6. Verify
    expected_delta = timedelta(minutes=test_interval_min)
    actual_delta = next_check - now
    
    # Allow a small margin of error for execution time (e.g., < 1 second)
    difference_seconds = abs(actual_delta.total_seconds() - expected_delta.total_seconds())
    
    assert difference_seconds < 1.0, (
        f"Expected delay of {test_interval_min} minutes ({expected_delta.total_seconds()}s), "
        f"but got {actual_delta.total_seconds()}s. "
        f"This implies NETWORK_ERROR is NOT mapping to on_server_error_min."
    )

    print(f"\nSUCCESS: NETWORK_ERROR correctly mapped to on_server_error_min ({test_interval_min}m)")
