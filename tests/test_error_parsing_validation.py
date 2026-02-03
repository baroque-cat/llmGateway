#!/usr/bin/env python3

"""
Tests for error parsing configuration validation.

This module tests the validation logic for error parsing configuration,
ensuring that error parsing rules are properly validated and invalid
configurations are rejected with appropriate error messages.
"""

from src.config.schemas import ErrorParsingConfig, ErrorParsingRule
from src.config.validator import ConfigValidator
from src.core.enums import ErrorReason


class TestErrorParsingValidation:
    """Test suite for error parsing configuration validation."""

    def test_valid_configuration_passes(self):
        """Test that a valid error parsing configuration passes validation."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="Arrearage|BillingHardLimit",
                    map_to="invalid_key",
                    priority=10,
                    description="Payment overdue or billing limit",
                ),
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.code",
                    match_pattern="insufficient_quota",
                    map_to="no_quota",
                    priority=5,
                    description="Insufficient quota",
                ),
            ],
        )

        # Should not raise any exception
        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 0

    def test_disabled_configuration_skips_validation(self):
        """Test that validation is skipped when error parsing is disabled."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=False,
            rules=[
                # This rule has invalid status code but should be ignored
                ErrorParsingRule(
                    status_code=200,  # Invalid: not 4xx or 5xx
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_key",
                )
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 0

    def test_invalid_status_code(self):
        """Test that non-4xx/5xx status codes are rejected."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=200,  # Invalid: success status code
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_key",
                ),
                ErrorParsingRule(
                    status_code=300,  # Invalid: redirect status code
                    error_path="error.code",
                    match_pattern="test",
                    map_to="no_quota",
                ),
                ErrorParsingRule(
                    status_code=600,  # Invalid: out of range
                    error_path="error.message",
                    match_pattern="test",
                    map_to="bad_request",
                ),
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 3

        errors = "\n".join(validator.errors)
        assert "status_code" in errors
        assert "must be a 4xx or 5xx HTTP status code" in errors
        assert "test_provider" in errors  # Provider name should be in error message

    def test_empty_error_path(self):
        """Test that empty error_path is rejected."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="",  # Empty string
                    match_pattern="test",
                    map_to="invalid_key",
                )
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 1

        errors = "\n".join(validator.errors)
        assert "error_path" in errors
        assert "must be a non-empty string" in errors

    def test_empty_match_pattern(self):
        """Test that empty match_pattern is rejected."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="",  # Empty string
                    map_to="invalid_key",
                )
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 1

        errors = "\n".join(validator.errors)
        assert "match_pattern" in errors
        assert "must be a non-empty string" in errors

    def test_invalid_map_to_value(self):
        """Test that invalid ErrorReason values are rejected."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_reason",  # Not a valid ErrorReason
                ),
                ErrorParsingRule(
                    status_code=429,
                    error_path="error.code",
                    match_pattern="rate_limit",
                    map_to="rate_limited",  # Valid value
                ),
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 1

        error = validator.errors[0]
        assert "map_to" in error
        assert "must be a valid ErrorReason value" in error
        assert "invalid_reason" in error

        # Check that valid values are listed in error message
        valid_values = [e.value for e in ErrorReason]
        for value in valid_values:
            if value == "rate_limited":
                continue  # This one is valid, might not be in error
            assert value in error

    def test_negative_priority(self):
        """Test that negative priority values are rejected."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_key",
                    priority=-1,  # Negative priority
                ),
                ErrorParsingRule(
                    status_code=429,
                    error_path="error.code",
                    match_pattern="rate_limit",
                    map_to="rate_limited",
                    priority=0,  # Valid: zero priority
                ),
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 1

        error = validator.errors[0]
        assert "priority" in error
        assert "must be non-negative" in error
        assert "-1" in error

    def test_multiple_errors_in_single_rule(self):
        """Test that a single rule with multiple issues reports all errors."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=200,  # Invalid status code
                    error_path="",  # Empty error_path
                    match_pattern="",  # Empty match_pattern
                    map_to="invalid_reason",  # Invalid map_to
                    priority=-5,  # Negative priority
                )
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        # Should have 4 errors: status_code, error_path, match_pattern, map_to, priority
        assert len(validator.errors) == 5

        errors = "\n".join(validator.errors)
        assert "status_code" in errors
        assert "error_path" in errors
        assert "match_pattern" in errors
        assert "map_to" in errors
        assert "priority" in errors

    def test_valid_status_code_ranges(self):
        """Test that valid 4xx and 5xx status codes are accepted."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,  # Valid: 4xx
                    error_path="error.type",
                    match_pattern="test",
                    map_to="bad_request",
                ),
                ErrorParsingRule(
                    status_code=404,  # Valid: 4xx
                    error_path="error.code",
                    match_pattern="not_found",
                    map_to="bad_request",
                ),
                ErrorParsingRule(
                    status_code=429,  # Valid: 4xx
                    error_path="error.message",
                    match_pattern="rate_limit",
                    map_to="rate_limited",
                ),
                ErrorParsingRule(
                    status_code=500,  # Valid: 5xx
                    error_path="error.type",
                    match_pattern="server_error",
                    map_to="server_error",
                ),
                ErrorParsingRule(
                    status_code=503,  # Valid: 5xx
                    error_path="error.code",
                    match_pattern="unavailable",
                    map_to="service_unavailable",
                ),
            ],
        )

        validator._validate_error_parsing("test_provider", config)
        assert len(validator.errors) == 0

    def test_error_messages_include_provider_name(self):
        """Test that error messages include the provider name for context."""
        validator = ConfigValidator()
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=200,  # Invalid
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_key",
                )
            ],
        )

        provider_name = "my_test_provider"
        validator._validate_error_parsing(provider_name, config)

        assert len(validator.errors) == 1
        error = validator.errors[0]
        assert provider_name in error
        assert "Provider 'my_test_provider'" in error
