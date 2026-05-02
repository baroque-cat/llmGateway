import pytest

from src.core.constants import (
    ErrorReason,
    ProviderType,
    ProxyMode,
)
from src.providers import _PROVIDER_CLASSES


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


# ==============================================================================
# Harden-config-validation: Enum existence and synchronization tests
# Reference: openspec/changes/harden-config-validation/test-plan.md, lines 131-136
# ==============================================================================


class TestProviderTypeEnumExistence:
    """
    Tests for ProviderType enum existence, members, and synchronization
    with _PROVIDER_CLASSES registry.
    """

    def test_provider_type_enum_exists_and_has_correct_members(self):
        """
        Verify that ProviderType is defined in src.core.constants and contains
        the expected members: ANTHROPIC, OPENAI_LIKE, GEMINI.
        """
        assert hasattr(
            ProviderType, "ANTHROPIC"
        ), "ProviderType should have ANTHROPIC member"
        assert hasattr(
            ProviderType, "OPENAI_LIKE"
        ), "ProviderType should have OPENAI_LIKE member"
        assert hasattr(ProviderType, "GEMINI"), "ProviderType should have GEMINI member"
        assert ProviderType.ANTHROPIC.value == "anthropic"
        assert ProviderType.OPENAI_LIKE.value == "openai_like"
        assert ProviderType.GEMINI.value == "gemini"

    def test_provider_type_values_match_provider_classes_keys(self):
        """
        Verify that the set of ProviderType enum values exactly matches
        the set of keys in _PROVIDER_CLASSES. This ensures the enum and
        the provider registry stay in sync.
        """
        enum_values = {p.value for p in ProviderType}
        registry_keys = set(_PROVIDER_CLASSES.keys())
        assert enum_values == registry_keys, (
            f"ProviderType values {enum_values} do not match "
            f"_PROVIDER_CLASSES keys {registry_keys}"
        )


class TestProxyModeEnumExistence:
    """
    Tests for ProxyMode enum existence and members.
    ProxyMode now has exactly 2 members: NONE and STATIC (STEALTH removed).
    """

    def test_proxy_mode_enum_has_none_and_static_only(self):
        """
        Verify that ProxyMode has exactly two members: NONE and STATIC.
        STEALTH has been removed.
        """
        assert hasattr(ProxyMode, "NONE"), "ProxyMode should have NONE member"
        assert hasattr(ProxyMode, "STATIC"), "ProxyMode should have STATIC member"
        assert ProxyMode.NONE.value == "none"
        assert ProxyMode.STATIC.value == "static"

    def test_proxy_mode_has_exactly_two_members(self):
        """
        Verify that ProxyMode has exactly 2 members (NONE, STATIC).
        """
        members = list(ProxyMode)
        assert len(members) == 2, f"Expected 2 members, got {len(members)}: {members}"
        assert members == [ProxyMode.NONE, ProxyMode.STATIC]

    def test_proxy_mode_stealth_does_not_exist(self):
        """
        Verify that ProxyMode.STEALTH has been removed.
        hasattr(ProxyMode, "STEALTH") → False
        ProxyMode("stealth") → ValueError
        """
        assert not hasattr(
            ProxyMode, "STEALTH"
        ), "ProxyMode should NOT have STEALTH member"
        with pytest.raises(ValueError):
            ProxyMode("stealth")


# ==============================================================================
# Section A: Circuit Breaker removal verification
# ==============================================================================


class TestCircuitBreakerRemoval:
    """
    Tests verifying that CircuitBreaker-related types have been completely removed.
    """

    def test_circuit_breaker_mode_import_raises_import_error(self):
        """
        CircuitBreakerMode import → ImportError.
        """
        with pytest.raises(ImportError):
            from src.core.constants import CircuitBreakerMode  # noqa: F401

    def test_circuit_breaker_config_import_raises_import_error(self):
        """
        CircuitBreakerConfig import → ImportError.
        """
        with pytest.raises(ImportError):
            from src.config.schemas import CircuitBreakerConfig  # noqa: F401

    def test_backoff_config_import_raises_import_error(self):
        """
        BackoffConfig import → ImportError.
        """
        with pytest.raises(ImportError):
            from src.config.schemas import BackoffConfig  # noqa: F401

    def test_gateway_policy_config_has_no_circuit_breaker_field(self):
        """
        GatewayPolicyConfig() has no circuit_breaker field.
        """
        from src.config.schemas import GatewayPolicyConfig

        policy = GatewayPolicyConfig()
        assert not hasattr(
            policy, "circuit_breaker"
        ), "GatewayPolicyConfig should NOT have a circuit_breaker field"

    def test_defaults_have_no_circuit_breaker_key(self):
        """
        GatewayPolicyConfig defaults have no "circuit_breaker" key.
        """
        from src.config.schemas import GatewayPolicyConfig

        policy = GatewayPolicyConfig()
        policy_dict = policy.model_dump()
        assert (
            "circuit_breaker" not in policy_dict
        ), f"'circuit_breaker' should not appear in defaults, got keys: {list(policy_dict.keys())}"


# ==============================================================================
# Section B: Proxy STEALTH removal verification
# ==============================================================================


class TestProxyStealthRemoval:
    """
    Tests verifying that STEALTH proxy mode and related types have been removed.
    """

    def test_proxy_config_has_no_pool_list_path_field(self):
        """
        ProxyConfig() has no pool_list_path field.
        """
        from src.config.schemas import ProxyConfig

        cfg = ProxyConfig()
        assert not hasattr(
            cfg, "pool_list_path"
        ), "ProxyConfig should NOT have a pool_list_path field"

    def test_proxy_config_stealth_mode_raises_validation_error(self):
        """
        ProxyConfig(mode="stealth") → ValidationError.
        """
        from pydantic import ValidationError

        from src.config.schemas import ProxyConfig

        with pytest.raises(ValidationError):
            ProxyConfig(mode="stealth")

    def test_provider_proxy_state_import_raises_import_error(self):
        """
        ProviderProxyState import → ImportError.
        """
        with pytest.raises(ImportError):
            from src.core.models import ProviderProxyState  # noqa: F401

    def test_defaults_have_no_pool_list_path_key(self):
        """
        ProxyConfig defaults have no "pool_list_path" key.
        """
        from src.config.schemas import ProxyConfig

        cfg = ProxyConfig()
        cfg_dict = cfg.model_dump()
        assert (
            "pool_list_path" not in cfg_dict
        ), f"'pool_list_path' should not appear in defaults, got keys: {list(cfg_dict.keys())}"


# ==============================================================================
# Section C: Binary ProxyMode positive tests
# ==============================================================================


class TestBinaryProxyModePositive:
    """
    Positive tests for the binary ProxyMode (NONE, STATIC) and ProxyConfig.
    """

    def test_proxy_mode_none_exists(self):
        """
        ProxyMode.NONE exists, value "none".
        """
        assert hasattr(ProxyMode, "NONE")
        assert ProxyMode.NONE.value == "none"

    def test_proxy_mode_static_exists(self):
        """
        ProxyMode.STATIC exists, value "static".
        """
        assert hasattr(ProxyMode, "STATIC")
        assert ProxyMode.STATIC.value == "static"

    def test_proxy_config_default_is_none_mode(self):
        """
        ProxyConfig() → mode == ProxyMode.NONE, static_url == None.
        """
        from src.config.schemas import ProxyConfig

        cfg = ProxyConfig()
        assert cfg.mode == ProxyMode.NONE
        assert cfg.static_url is None

    def test_proxy_config_mode_none_is_valid(self):
        """
        ProxyConfig(mode="none") → valid.
        """
        from src.config.schemas import ProxyConfig

        cfg = ProxyConfig(mode="none")
        assert cfg.mode == ProxyMode.NONE

    def test_proxy_config_mode_static_with_url_is_valid(self):
        """
        ProxyConfig(mode="static", static_url="http://proxy:8080") → valid.
        """
        from src.config.schemas import ProxyConfig

        cfg = ProxyConfig(mode="static", static_url="http://proxy:8080")
        assert cfg.mode == ProxyMode.STATIC
        assert cfg.static_url == "http://proxy:8080"

    def test_proxy_config_static_without_url_raises_validation_error(self):
        """
        ProxyConfig(mode="static") without static_url → ValidationError mentioning "static_url".
        """
        from pydantic import ValidationError

        from src.config.schemas import ProxyConfig

        with pytest.raises(ValidationError, match="static_url"):
            ProxyConfig(mode="static")

    def test_proxy_config_invalid_mode_raises_validation_error_without_stealth(self):
        """
        ProxyConfig(mode="invalid") → ValidationError, message contains "none" and "static"
        but NOT "stealth".
        """
        from pydantic import ValidationError

        from src.config.schemas import ProxyConfig

        with pytest.raises(ValidationError) as exc_info:
            ProxyConfig(mode="invalid")

        error_msg = str(exc_info.value)
        assert (
            "none" in error_msg.lower()
        ), f"Error message should mention 'none', got: {error_msg}"
        assert (
            "static" in error_msg.lower()
        ), f"Error message should mention 'static', got: {error_msg}"
        assert (
            "stealth" not in error_msg.lower()
        ), f"Error message should NOT mention 'stealth', got: {error_msg}"
