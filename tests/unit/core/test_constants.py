from src.core.constants import ErrorReason


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
            ErrorReason.STREAM_DISCONNECT,
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

    def test_is_client_error_method(self):
        """
        Verify the is_client_error() method correctly identifies client-side errors.
        After the fix, UNKNOWN should also be considered a client error to prevent unfair penalties.
        """
        # These errors should be considered client errors
        client_errors = [
            ErrorReason.BAD_REQUEST,
            ErrorReason.UNKNOWN,
        ]

        for error in client_errors:
            assert error.is_client_error() is True, f"{error} should be a client error"

        # These errors should NOT be client errors
        non_client_errors = [
            ErrorReason.INVALID_KEY,
            ErrorReason.NO_ACCESS,
            ErrorReason.RATE_LIMITED,
            ErrorReason.NO_QUOTA,
            ErrorReason.NO_MODEL,
            ErrorReason.NETWORK_ERROR,
            ErrorReason.TIMEOUT,
            ErrorReason.SERVER_ERROR,
            ErrorReason.SERVICE_UNAVAILABLE,
            ErrorReason.OVERLOADED,
            ErrorReason.STREAM_DISCONNECT,
        ]

        for error in non_client_errors:
            assert (
                error.is_client_error() is False
            ), f"{error} should NOT be a client error"

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
            ErrorReason.STREAM_DISCONNECT,
        ]

        for error in non_fatal_errors:
            assert error.is_fatal() is False, f"{error} should NOT be fatal"


class TestStreamDisconnect:
    """
    Tests for the new ErrorReason.STREAM_DISCONNECT enum member.

    STREAM_DISCONNECT represents an upstream provider dropping a streaming
    connection. It is classified as a server-side, retryable error — not
    fatal and not a client error.
    """

    def test_stream_disconnect_value(self):
        """
        5.1: STREAM_DISCONNECT exists and has value "stream_disconnect".
        """
        assert hasattr(
            ErrorReason, "STREAM_DISCONNECT"
        ), "ErrorReason should have STREAM_DISCONNECT member"
        assert (
            ErrorReason.STREAM_DISCONNECT.value == "stream_disconnect"
        ), f"Expected value 'stream_disconnect', got '{ErrorReason.STREAM_DISCONNECT.value}'"

    def test_stream_disconnect_is_retryable(self):
        """
        5.2: STREAM_DISCONNECT.is_retryable() → True.
        """
        assert (
            ErrorReason.STREAM_DISCONNECT.is_retryable() is True
        ), "STREAM_DISCONNECT should be retryable"

    def test_stream_disconnect_is_server_error(self):
        """
        5.3: STREAM_DISCONNECT.is_server_error() → True.
        """
        assert (
            ErrorReason.STREAM_DISCONNECT.is_server_error() is True
        ), "STREAM_DISCONNECT should be a server error"

    def test_stream_disconnect_is_not_fatal(self):
        """
        5.4: STREAM_DISCONNECT.is_fatal() → False.
        """
        assert (
            ErrorReason.STREAM_DISCONNECT.is_fatal() is False
        ), "STREAM_DISCONNECT should NOT be fatal"

    def test_stream_disconnect_is_not_client_error(self):
        """
        5.5: STREAM_DISCONNECT.is_client_error() → False.
        """
        assert (
            ErrorReason.STREAM_DISCONNECT.is_client_error() is False
        ), "STREAM_DISCONNECT should NOT be a client error"
