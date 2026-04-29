#!/usr/bin/env python3

"""
Tests for error parsing configuration validation with Pydantic v2.

With the migration from dataclasses + ConfigValidator to Pydantic v2 BaseModel,
validation is now performed inline during model construction via Field constraints
and model_validator. This test suite verifies the Pydantic-level validation and
documents validation gaps that were previously handled by ConfigValidator.

Key changes from ConfigValidator to Pydantic:
- status_code: Now validated by Field(ge=400, lt=600) ✅
- priority: Now validated by Field(default=0, ge=0) ✅
- error_path: Required str field, but empty string "" is accepted ⚠️ (was rejected by ConfigValidator)
- match_pattern: Required str field, but empty string "" is accepted ⚠️ (was rejected by ConfigValidator)
- map_to: Plain str field, any string accepted ⚠️ (was checked against ErrorReason enum by ConfigValidator)
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import ErrorParsingConfig, ErrorParsingRule
from src.core.constants import ErrorReason


class TestErrorParsingValidation:
    """Test suite for error parsing configuration validation with Pydantic v2."""

    def test_valid_configuration_passes(self):
        """Test that a valid error parsing configuration passes Pydantic validation."""
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

        assert config.enabled is True
        assert len(config.rules) == 2

    def test_disabled_configuration_skips_validation(self):
        """Test that disabled error parsing config is valid regardless of rule content."""
        # When error_parsing.enabled=False, the rules are still validated by Pydantic
        # at the schema level. However, the application logic skips using them.
        # A rule with status_code=200 would fail Pydantic's Field(ge=400) constraint,
        # so we use a valid status code here.
        config = ErrorParsingConfig(
            enabled=False,
            rules=[
                ErrorParsingRule(
                    status_code=400,  # Valid per Pydantic constraint
                    error_path="error.type",
                    match_pattern="test",
                    map_to="invalid_key",
                )
            ],
        )

        assert config.enabled is False
        assert len(config.rules) == 1

    def test_invalid_status_code_below_400(self):
        """Test that status codes below 400 are rejected by Pydantic Field(ge=400)."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=200,
                error_path="error.type",
                match_pattern="test",
                map_to="invalid_key",
            )

        error_message = str(exc_info.value)
        assert "status_code" in error_message
        assert "400" in error_message or "greater than or equal to 400" in error_message

    def test_invalid_status_code_redirect(self):
        """Test that 3xx redirect status codes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=300,
                error_path="error.code",
                match_pattern="test",
                map_to="no_quota",
            )

        error_message = str(exc_info.value)
        assert "status_code" in error_message

    def test_invalid_status_code_above_599(self):
        """Test that status codes >= 600 are rejected by Pydantic Field(lt=600)."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=600,
                error_path="error.message",
                match_pattern="test",
                map_to="bad_request",
            )

        error_message = str(exc_info.value)
        assert "status_code" in error_message
        assert "600" in error_message or "less than 600" in error_message

    def test_empty_error_path_accepted_by_pydantic(self):
        """
        Test that empty error_path is accepted by Pydantic (str field accepts "").

        NOTE: error_path="" is now a meaningful value that enables fulltext
        search mode in _refine_error_reason. The regex is applied against
        the entire raw response body instead of a specific JSON field.
        This is equivalent to error_path="$" (also fulltext mode).
        """
        rule = ErrorParsingRule(
            status_code=400,
            error_path="",  # Empty string - accepted by Pydantic str type
            match_pattern="test",
            map_to="invalid_key",
        )
        assert rule.error_path == ""

    def test_empty_match_pattern_accepted_by_pydantic(self):
        """
        Test that empty match_pattern is accepted by Pydantic (str field accepts "").

        NOTE: This was previously rejected by ConfigValidator with "must be a non-empty string".
        With Pydantic v2, the match_pattern field is a required str, which accepts empty strings.
        This is a known validation gap.
        """
        rule = ErrorParsingRule(
            status_code=400,
            error_path="error.type",
            match_pattern="",  # Empty string - accepted by Pydantic str type
            map_to="invalid_key",
        )
        assert rule.match_pattern == ""

    def test_invalid_map_to_value_rejected_by_pydantic(self):
        """
        Test that invalid map_to values are rejected by Pydantic.

        NOTE: map_to is now typed as ErrorReason enum in ErrorParsingRule.
        Previously, map_to was a plain str field that accepted any string,
        and validation was done by ConfigValidator at runtime. Now, Pydantic
        enforces that map_to must be a valid ErrorReason value at construction
        time, eliminating the validation gap.
        """
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="test",
                map_to="invalid_reason",  # Not a valid ErrorReason
            )

        error_message = str(exc_info.value)
        assert "map_to" in error_message
        assert "invalid_reason" in error_message

    def test_valid_map_to_values(self):
        """Test that valid ErrorReason string values are accepted and coerced to enum."""
        valid_reasons = [
            ("bad_request", ErrorReason.BAD_REQUEST),
            ("invalid_key", ErrorReason.INVALID_KEY),
            ("no_quota", ErrorReason.NO_QUOTA),
            ("rate_limited", ErrorReason.RATE_LIMITED),
            ("server_error", ErrorReason.SERVER_ERROR),
        ]
        for reason_str, expected_enum in valid_reasons:
            rule = ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="test",
                map_to=reason_str,
            )
            assert rule.map_to == expected_enum
            assert rule.map_to.value == reason_str

    def test_negative_priority_rejected(self):
        """Test that negative priority values are rejected by Pydantic Field(ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="test",
                map_to="invalid_key",
                priority=-1,
            )

        error_message = str(exc_info.value)
        assert "priority" in error_message
        assert "-1" in error_message or "greater than or equal to 0" in error_message

    def test_zero_priority_accepted(self):
        """Test that zero priority is valid (Field default=0, ge=0)."""
        rule = ErrorParsingRule(
            status_code=400,
            error_path="error.type",
            match_pattern="test",
            map_to="invalid_key",
            priority=0,
        )
        assert rule.priority == 0

    def test_valid_status_code_ranges(self):
        """Test that valid 4xx and 5xx status codes are accepted."""
        valid_codes = [400, 404, 429, 500, 503]
        for code in valid_codes:
            rule = ErrorParsingRule(
                status_code=code,
                error_path="error.type",
                match_pattern="test",
                map_to="bad_request",
            )
            assert rule.status_code == code

    def test_error_parsing_config_default_rules(self):
        """Test that ErrorParsingConfig default rules is an empty list."""
        config = ErrorParsingConfig()
        assert config.enabled is False
        assert config.rules == []

    def test_error_parsing_config_with_rules(self):
        """Test ErrorParsingConfig with explicit rules."""
        config = ErrorParsingConfig(
            enabled=True,
            rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.status",
                    match_pattern="INVALID_ARGUMENT",
                    map_to="invalid_key",
                    priority=10,
                ),
            ],
        )
        assert config.enabled is True
        assert len(config.rules) == 1
        assert config.rules[0].status_code == 400

    def test_error_reason_enum_values_available(self):
        """Verify ErrorReason enum values for reference in map_to validation gap docs."""
        valid_values = [e.value for e in ErrorReason]
        # These are the values that ConfigValidator used to check against
        assert "bad_request" in valid_values
        assert "invalid_key" in valid_values
        assert "no_quota" in valid_values
        assert "rate_limited" in valid_values
        assert "server_error" in valid_values
