#!/usr/bin/env python3

"""
Test suite for Pydantic v2 configuration validation.

These tests verify that the Pydantic BaseModel schemas correctly reject invalid
values at the model_validate() boundary. With the migration from dataclasses +
ConfigValidator to Pydantic v2 BaseModel, validation is now performed inline
during model construction rather than in a separate post-load validation step.

Group G1 tests: Updated for enum-based validation (harden-config-validation).
Group G2 tests: UT-B01..UT-B10, UT-C01..UT-C04, UT-H12, UT-H13
Covering: HealthPolicyConfig batch-field removal & default updates,
          TimeoutConfig default updates, YAML legacy/new format validation.
Integration/E2E and Security tests for enum validation.
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    AdaptiveBatchingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    HealthPolicyConfig,
    ProviderConfig,
    ProxyConfig,
    TimeoutConfig,
)
from src.core.constants import (
    CircuitBreakerMode,
    DebugMode,
    ProviderType,
    ProxyMode,
    StreamingMode,
)

# ==============================================================================
# G1: Updated existing tests for enum-based validation
# ==============================================================================


def test_invalid_debug_mode_should_fail_validation():
    """
    Test that a typo in debug_mode (e.g., 'diabled') causes Pydantic
    ValidationError during config loading via YAML.

    After replacing Literal with DebugMode enum, the validation error message
    should list the valid enum member values.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "diabled"  # This is the typo we want to catch
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        # Pydantic validation now happens inside loader.load() via model_validate()
        # handle_validation_error calls sys.exit(1), so we catch that
        with pytest.raises(SystemExit):
            loader.load()


def test_invalid_debug_mode_direct_schema_validation():
    """
    Test that GatewayPolicyConfig directly rejects invalid debug_mode values
    via Pydantic DebugMode enum validation.

    After replacing Literal with DebugMode enum, the error message should
    contain the valid enum member values (disabled, no_content, full_body).
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(debug_mode="diabled")

    error_message = str(exc_info.value)
    # With enum validation, Pydantic lists the valid enum member values
    assert "diabled" in error_message
    # Verify that the error message references the valid DebugMode enum members
    assert "disabled" in error_message
    assert "no_content" in error_message
    assert "full_body" in error_message


def test_invalid_streaming_mode_should_fail_validation():
    """
    Test that an invalid streaming_mode value causes Pydantic ValidationError
    during config loading via YAML.

    After replacing Literal with StreamingMode enum, the validation error
    message should list the valid enum member values.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      streaming_mode: "full_stream"  # Invalid value
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_invalid_streaming_mode_direct_schema_validation():
    """
    Test that GatewayPolicyConfig directly rejects invalid streaming_mode values
    via Pydantic StreamingMode enum validation.

    After replacing Literal with StreamingMode enum, the error message should
    contain the valid enum member values (auto, disabled).
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(streaming_mode="full_stream")

    error_message = str(exc_info.value)
    assert "full_stream" in error_message
    # Verify that the error message references the valid StreamingMode enum members
    assert "auto" in error_message
    assert "disabled" in error_message


def test_valid_config_should_pass_validation():
    """
    Ensure that a completely valid configuration passes Pydantic validation
    during config loading, with all enum fields properly coerced.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "disabled"
      streaming_mode: "auto"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify the config loaded correctly with enum comparisons
        provider = config.providers["test_provider"]
        assert provider.gateway_policy.debug_mode == DebugMode.DISABLED
        assert provider.gateway_policy.streaming_mode == StreamingMode.AUTO


# ==============================================================================
# Preserved tests (not in G1 scope but need provider_type fix)
# ==============================================================================


def test_provider_config_extra_fields_forbidden():
    """
    Test that ProviderConfig rejects extra fields (Pydantic extra="forbid").
    This replaces the old ConfigValidator's strict validation approach.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(
            provider_type="openai_like",
            unknown_field="should_be_rejected",
        )

    error_message = str(exc_info.value)
    assert (
        "unknown_field" in error_message
        or "Extra inputs are not permitted" in error_message
    )


def test_health_policy_quarantine_logic():
    """
    Test that HealthPolicyConfig model_validator rejects quarantine_after_days
    greater than stop_checking_after_days.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(
            quarantine_after_days=100,
            stop_checking_after_days=50,
        )

    error_message = str(exc_info.value)
    assert "quarantine_after_days" in error_message


def test_duplicate_gateway_tokens_rejected():
    """
    Test that Config model_validator rejects duplicate gateway_access_token
    across enabled providers.
    """
    from src.config.schemas import Config

    with pytest.raises(ValidationError) as exc_info:
        Config.model_validate(
            {
                "providers": {
                    "provider_a": {
                        "provider_type": "openai_like",
                        "enabled": True,
                        "access_control": {"gateway_access_token": "same_token"},
                    },
                    "provider_b": {
                        "provider_type": "openai_like",
                        "enabled": True,
                        "access_control": {"gateway_access_token": "same_token"},
                    },
                }
            }
        )

    error_message = str(exc_info.value)
    assert "Duplicate gateway_access_token" in error_message


# ==============================================================================
# UT-B01..UT-B10: HealthPolicyConfig — batch-field removal & default updates
# ==============================================================================


def test_ut_b01_health_policy_batch_size_rejected():
    """
    UT-B01: HealthPolicyConfig does not contain field batch_size.
    Attempting to create HealthPolicyConfig(batch_size=10) should raise
    ValidationError because the field has been removed and replaced by
    adaptive_batching.start_batch_size.

    NOTE: This test requires HealthPolicyConfig to have extra="forbid".
    If HealthPolicyConfig does not forbid extra fields, batch_size will be
    silently ignored instead of raising ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(batch_size=10)

    error_message = str(exc_info.value)
    assert "batch_size" in error_message


def test_ut_b02_health_policy_batch_delay_sec_rejected():
    """
    UT-B02: HealthPolicyConfig does not contain field batch_delay_sec.
    Attempting to create HealthPolicyConfig(batch_delay_sec=15) should raise
    ValidationError because the field has been removed and replaced by
    adaptive_batching.start_batch_delay_sec.

    NOTE: This test requires HealthPolicyConfig to have extra="forbid".
    If HealthPolicyConfig does not forbid extra fields, batch_delay_sec will be
    silently ignored instead of raising ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(batch_delay_sec=15)

    error_message = str(exc_info.value)
    assert "batch_delay_sec" in error_message


def test_ut_b03_yaml_batch_size_under_worker_health_policy_causes_error():
    """
    UT-B03: YAML config with batch_size under worker_health_policy causes
    ValidationError when loaded through ConfigLoader.

    NOTE: This test requires HealthPolicyConfig to have extra="forbid".
    If HealthPolicyConfig does not forbid extra fields, batch_size will be
    silently ignored during YAML loading instead of causing a ValidationError.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    worker_health_policy:
      batch_size: 10
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        # ConfigLoader.load() calls handle_validation_error on ValidationError,
        # which calls sys.exit(1)
        with pytest.raises(SystemExit):
            loader.load()


def test_ut_b04_health_policy_adaptive_batching_default_factory():
    """
    UT-B04: HealthPolicyConfig.adaptive_batching is always populated via
    default_factory. When creating HealthPolicyConfig() without specifying
    adaptive_batching, it should have start_batch_size=30 and
    start_batch_delay_sec=15.0 (the defaults from AdaptiveBatchingConfig).
    """
    policy = HealthPolicyConfig()

    assert isinstance(policy.adaptive_batching, AdaptiveBatchingConfig)
    assert policy.adaptive_batching.start_batch_size == 30
    assert policy.adaptive_batching.start_batch_delay_sec == 15.0


def test_ut_b05_health_policy_default_on_success_hr():
    """
    UT-B05: Default on_success_hr is 24 (updated from old value of 1).
    """
    policy = HealthPolicyConfig()
    assert policy.on_success_hr == 24


def test_ut_b06_health_policy_default_on_rate_limit_hr():
    """
    UT-B06: Default on_rate_limit_hr is 1 (updated from old value of 4).
    """
    policy = HealthPolicyConfig()
    assert policy.on_rate_limit_hr == 1


def test_ut_b07_health_policy_default_on_no_quota_hr():
    """
    UT-B07: Default on_no_quota_hr is 6 (updated from old value of 4).
    """
    policy = HealthPolicyConfig()
    assert policy.on_no_quota_hr == 6


def test_ut_b08_health_policy_default_on_overload_min():
    """
    UT-B08: Default on_overload_min is 30 (updated from old value of 60).
    """
    policy = HealthPolicyConfig()
    assert policy.on_overload_min == 30


def test_ut_b09_health_policy_default_on_server_error_min():
    """
    UT-B09: Default on_server_error_min is 30.
    """
    policy = HealthPolicyConfig()
    assert policy.on_server_error_min == 30


def test_ut_b10_health_policy_default_on_other_error_hr():
    """
    UT-B10: Default on_other_error_hr is 1.
    """
    policy = HealthPolicyConfig()
    assert policy.on_other_error_hr == 1


# ==============================================================================
# UT-C01..UT-C04: TimeoutConfig — default updates
# ==============================================================================


def test_ut_c01_timeout_config_default_connect():
    """
    UT-C01: Default TimeoutConfig.connect is 15.0 (updated from old value of 5.0).
    """
    timeouts = TimeoutConfig()
    assert timeouts.connect == 15.0


def test_ut_c02_timeout_config_default_read():
    """
    UT-C02: Default TimeoutConfig.read is 300.0 (updated from old value of 20.0).
    """
    timeouts = TimeoutConfig()
    assert timeouts.read == 300.0


def test_ut_c03_timeout_config_default_write():
    """
    UT-C03: Default TimeoutConfig.write is 35.0 (updated from old value of 10.0).
    """
    timeouts = TimeoutConfig()
    assert timeouts.write == 35.0


def test_ut_c04_timeout_config_default_pool():
    """
    UT-C04: Default TimeoutConfig.pool is 35.0 (updated from old value of 5.0).
    """
    timeouts = TimeoutConfig()
    assert timeouts.pool == 35.0


# ==============================================================================
# UT-H12, UT-H13: YAML legacy/new format validation
# ==============================================================================


def test_ut_h12_legacy_batch_size_in_yaml_causes_validation_error():
    """
    UT-H12: Legacy batch_size in YAML under worker_health_policy causes
    ValidationError when loaded through ConfigLoader.

    NOTE: This test requires HealthPolicyConfig to have extra="forbid".
    If HealthPolicyConfig does not forbid extra fields, batch_size will be
    silently ignored during YAML loading instead of causing a ValidationError.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    worker_health_policy:
      batch_size: 10
      batch_delay_sec: 15
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        # ConfigLoader.load() calls handle_validation_error on ValidationError,
        # which calls sys.exit(1)
        with pytest.raises(SystemExit):
            loader.load()


def test_ut_h13_new_format_yaml_with_start_batch_size_is_valid():
    """
    UT-H13: New format YAML with start_batch_size inside adaptive_batching
    under worker_health_policy is valid and loads successfully.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    worker_health_policy:
      adaptive_batching:
        start_batch_size: 10
        start_batch_delay_sec: 30.0
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify the config loaded correctly with the new adaptive_batching fields
        provider = config.providers["test_provider"]
        assert provider.worker_health_policy.adaptive_batching.start_batch_size == 10
        assert (
            provider.worker_health_policy.adaptive_batching.start_batch_delay_sec
            == 30.0
        )


# ==============================================================================
# G2: ProviderConfig.dedicated_http_client — default, explicit, type validation,
#     YAML parsing
# ==============================================================================


def test_g2_1_1_dedicated_http_client_default_is_false():
    """
    G2-1.1: ProviderConfig.dedicated_http_client defaults to False when the
    field is not explicitly provided.
    """
    provider = ProviderConfig(provider_type="openai_like")
    assert provider.dedicated_http_client is False


def test_g2_1_2_dedicated_http_client_explicit_true():
    """
    G2-1.2: ProviderConfig.dedicated_http_client can be explicitly set to True.
    """
    provider = ProviderConfig(provider_type="openai_like", dedicated_http_client=True)
    assert provider.dedicated_http_client is True


def test_g2_1_3_dedicated_http_client_invalid_type_raises_validation_error():
    """
    G2-1.3: ProviderConfig rejects a non-bool value for dedicated_http_client.

    Passing a string like "yes" should raise ValidationError because
    dedicated_http_client is typed as bool. However, Pydantic v2 in lax
    (default) mode coerces certain string values ("yes", "no", "true",
    "false", "1", "0") to bool. To reliably trigger a ValidationError,
    we pass a type that Pydantic cannot coerce to bool (e.g., a list).
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(
            provider_type="openai_like",
            dedicated_http_client=["yes"],
        )

    error_message = str(exc_info.value)
    assert "dedicated_http_client" in error_message


def test_g2_1_4_yaml_dedicated_http_client_true():
    """
    G2-1.4: YAML config with dedicated_http_client: true loads correctly
    and the provider's dedicated_http_client field is True.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    dedicated_http_client: true
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.dedicated_http_client is True


def test_g2_1_5_yaml_dedicated_http_client_absent_defaults_to_false():
    """
    G2-1.5: YAML config without dedicated_http_client field loads correctly
    and the provider's dedicated_http_client defaults to False.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.dedicated_http_client is False


# ==============================================================================
# Integration / E2E Tests (from test-plan, not fitting in other group files)
# ==============================================================================


def test_full_valid_config_with_all_enums_loads_via_yaml():
    """
    Integration: Full YAML config with all enum fields loads successfully,
    and all values are properly coerced to their enum types.
    """
    mock_yaml_content = """providers:
  gemini_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://generativelanguage.googleapis.com/v1beta"
    access_control:
      gateway_access_token: "gemini_token"
    proxy_config:
      mode: "none"
    gateway_policy:
      debug_mode: "no_content"
      streaming_mode: "auto"
      circuit_breaker:
        mode: "auto_recovery"
      retry:
        enabled: false
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["gemini_provider"]
        # Verify all enum fields are properly coerced
        assert provider.provider_type == ProviderType.GEMINI
        assert provider.gateway_policy.debug_mode == DebugMode.NO_CONTENT
        assert provider.gateway_policy.streaming_mode == StreamingMode.AUTO
        assert provider.proxy_config.mode == ProxyMode.NONE
        assert (
            provider.gateway_policy.circuit_breaker.mode
            == CircuitBreakerMode.AUTO_RECOVERY
        )


# ==============================================================================
# Security Tests (from test-plan, not fitting in other group files)
# ==============================================================================


def test_provider_type_injection_rejected():
    """
    Security: ProviderConfig rejects SQL injection-style provider_type values.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(provider_type="; DROP TABLE keys;")

    error_message = str(exc_info.value)
    # The error should list valid ProviderType enum members
    assert (
        "anthropic" in error_message
        or "openai_like" in error_message
        or "gemini" in error_message
    )


def test_proxy_mode_injection_rejected():
    """
    Security: ProxyConfig rejects shell injection-style mode values.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="none; rm -rf /")

    error_message = str(exc_info.value)
    # The error should list valid ProxyMode enum members
    assert (
        "none" in error_message
        or "static" in error_message
        or "stealth" in error_message
    )


def test_error_reason_injection_in_fast_status_mapping_rejected():
    """
    Security: GatewayPolicyConfig rejects SQL injection-style ErrorReason
    values in fast_status_mapping.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(fast_status_mapping={400: "'; DROP TABLE"})

    error_message = str(exc_info.value)
    # The error should indicate the value is not a valid ErrorReason
    assert "DROP TABLE" in error_message or "enum" in error_message.lower()


def test_error_reason_injection_in_map_to_rejected():
    """
    Security: ErrorParsingRule rejects code injection-style map_to values.
    """
    with pytest.raises(ValidationError) as exc_info:
        ErrorParsingRule(
            status_code=400, error_path="e", match_pattern="x", map_to="'; exec"
        )

    error_message = str(exc_info.value)
    # The error should indicate the value is not a valid ErrorReason
    assert "exec" in error_message or "enum" in error_message.lower()


def test_regex_dos_pattern_compiles_but_documented():
    """
    Security: ErrorParsingRule accepts a potentially dangerous regex pattern
    (ReDoS-vulnerable). The field_validator only checks compilability, not
    security. Protection against ReDoS requires re.compile(pattern, timeout=...)
    (Python 3.13+). This test documents the current behavior.
    """
    # This pattern is a classic ReDoS-vulnerable regex, but it compiles fine
    rule = ErrorParsingRule(
        status_code=400, error_path="e", match_pattern="(a+)+$", map_to="invalid_key"
    )
    assert rule.match_pattern == "(a+)+$"
    # NOTE: This test documents that the validator only checks compilability,
    # not ReDoS safety. A timeout-based re.compile would be needed for full protection.


# ==============================================================================
# C5: Provider name validation tests
# ==============================================================================


def test_valid_provider_name_passes():
    """Valid provider names (alphanumeric, hyphens, underscores) pass validation."""
    from src.config.schemas import Config, ProviderConfig

    providers = {
        "gemini-pro-home": ProviderConfig(provider_type="gemini"),
        "deepseek_home": ProviderConfig(provider_type="openai_like"),
        "test123": ProviderConfig(provider_type="gemini"),
    }
    config = Config(providers=providers)
    assert "gemini-pro-home" in config.providers


def test_invalid_name_with_slash_rejected():
    """Provider name with slash raises ValidationError."""
    from src.config.schemas import Config, ProviderConfig

    with pytest.raises(ValidationError):
        Config(providers={"bad/name": ProviderConfig(provider_type="gemini")})


def test_invalid_name_with_dot_dot_rejected():
    """Provider name with .. raises ValidationError."""
    from src.config.schemas import Config, ProviderConfig

    with pytest.raises(ValidationError):
        Config(providers={"../escape": ProviderConfig(provider_type="gemini")})


def test_invalid_name_with_space_rejected():
    """Provider name with space raises ValidationError."""
    from src.config.schemas import Config, ProviderConfig

    with pytest.raises(ValidationError):
        Config(providers={"bad name": ProviderConfig(provider_type="gemini")})


def test_invalid_name_with_special_chars_rejected():
    """Provider name with special chars raises ValidationError."""
    from src.config.schemas import Config, ProviderConfig

    with pytest.raises(ValidationError):
        Config(providers={"name@!": ProviderConfig(provider_type="gemini")})


# ==============================================================================
# C6: keys_path rejection tests
# ==============================================================================


def test_keys_path_in_yaml_raises_validation_error():
    """YAML with keys_path raises ValidationError (extra field forbidden)."""
    import yaml

    from src.config.schemas import Config

    yaml_content = """
providers:
  test-provider:
    provider_type: gemini
    enabled: true
    keys_path: keys/test/
"""
    data = yaml.safe_load(yaml_content)
    with pytest.raises(ValidationError):
        Config(**data)


def test_provider_config_valid_without_keys_path():
    """ProviderConfig without keys_path is valid."""
    from src.config.schemas import ProviderConfig

    provider = ProviderConfig(provider_type="gemini")
    assert provider.provider_type.value == "gemini"


def test_keys_path_attribute_does_not_exist():
    """ProviderConfig has no keys_path attribute."""
    from src.config.schemas import ProviderConfig

    provider = ProviderConfig(provider_type="gemini")
    assert not hasattr(provider, "keys_path")



