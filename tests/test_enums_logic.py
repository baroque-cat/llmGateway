import pytest
from src.core.enums import ErrorReason

class TestErrorReasonLogic:
    """
    Tests for ErrorReason enum logic, specifically is_retryable() and is_fatal().
    """

    def test_retryable_errors(self):
        """
        Verify that transient errors are considered retryable.
        """
        retryable = [
            ErrorReason.NETWORK_ERROR,
            ErrorReason.TIMEOUT,
            ErrorReason.SERVER_ERROR,
            ErrorReason.SERVICE_UNAVAILABLE,
            ErrorReason.OVERLOADED,
            ErrorReason.RATE_LIMITED,
        ]
        
        for error in retryable:
            assert error.is_retryable() is True, f"{error} should be retryable"

    def test_fatal_errors_are_not_retryable(self):
        """
        Verify that fatal errors (requiring key change) are NOT retryable.
        This fixes the logical error where INVALID_KEY was considered retryable.
        """
        fatal_non_retryable = [
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
            ErrorReason.NO_QUOTA,
            ErrorReason.NO_MODEL,
        ]
        
        for error in fatal_non_retryable:
            assert error.is_retryable() is False, f"{error} should NOT be retryable"

    def test_client_errors_are_not_retryable(self):
        """
        Verify that client errors (bad request) are not retryable.
        """
        assert ErrorReason.BAD_REQUEST.is_retryable() is False

    def test_is_fatal_method(self):
        """
        Verify the new is_fatal() method correctly identifies key-invalidating errors.
        """
        # These errors require the key to be disabled/marked invalid
        fatal_errors = [
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
            ErrorReason.NO_QUOTA,
            ErrorReason.NO_MODEL,
        ]
        
        for error in fatal_errors:
            assert error.is_fatal() is True, f"{error} should be fatal"

        # These errors should NOT be fatal (transient or benign)
        non_fatal_errors = [
            ErrorReason.NETWORK_ERROR,
            ErrorReason.TIMEOUT,
            ErrorReason.SERVER_ERROR,
            ErrorReason.SERVICE_UNAVAILABLE,
            ErrorReason.OVERLOADED,
            ErrorReason.RATE_LIMITED,
            ErrorReason.BAD_REQUEST,
            ErrorReason.UNKNOWN,
        ]
        
        for error in non_fatal_errors:
            assert error.is_fatal() is False, f"{error} should NOT be fatal"
