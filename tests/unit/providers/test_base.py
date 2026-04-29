#!/usr/bin/env python3

"""
Tests for base provider error parsing logic.

This module tests the core error parsing functionality in AIBaseProvider,
including JSON value extraction and error reason refinement based on
configured parsing rules.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.providers.base import AIBaseProvider


class MockAIBaseProvider(AIBaseProvider):
    """
    Mock implementation of AIBaseProvider for testing.

    Implements all abstract methods with minimal functionality.
    """

    def _get_headers(self, token: str) -> dict[str, str] | None:
        return {}

    async def _parse_proxy_error(
        self, response: httpx.Response, content: bytes | None = None
    ) -> CheckResult:
        return CheckResult.fail(ErrorReason.UNKNOWN)

    async def check(
        self, client: httpx.AsyncClient, token: str, **kwargs
    ) -> CheckResult:
        return CheckResult.success()

    async def inspect(
        self, client: httpx.AsyncClient, token: str, **kwargs
    ) -> list[str]:
        return []

    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        return RequestDetails(model_name="test")

    async def proxy_request(
        self,
        client: httpx.AsyncClient,
        token: str,
        method: str,
        headers: dict,
        path: str,
        query_params: str,
        content: bytes,
    ) -> tuple[httpx.Response, CheckResult]:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        return mock_response, CheckResult.success()


class TestErrorParsingBase:
    """Test suite for base provider error parsing functionality."""

    def create_mock_provider(self, error_config=None):
        """Helper to create a mock provider with given error parsing configuration."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)

        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])

        mock_config.error_parsing = error_config

        # Create provider instance using our mock implementation
        provider = MockAIBaseProvider("test_provider", mock_config)
        return provider

    # --- Tests for _extract_json_value ---

    def test_extract_json_value_simple_path(self):
        """Test extracting values with simple dot-separated paths."""
        provider = self.create_mock_provider()

        data = {
            "error": {"type": "Arrearage", "code": 1001, "message": "Payment overdue"}
        }

        # Test valid paths
        assert provider._extract_json_value(data, "error.type") == "Arrearage"
        assert provider._extract_json_value(data, "error.code") == 1001
        assert provider._extract_json_value(data, "error.message") == "Payment overdue"

        # Test non-existent path
        assert provider._extract_json_value(data, "error.nonexistent") is None
        assert provider._extract_json_value(data, "nonexistent.field") is None

        # Test empty path
        assert provider._extract_json_value(data, "") is None

    def test_extract_json_value_nested_path(self):
        """Test extracting values from deeply nested structures."""
        provider = self.create_mock_provider()

        data = {
            "response": {
                "error": {"details": {"type": "billing", "subtype": "hard_limit"}}
            }
        }

        assert (
            provider._extract_json_value(data, "response.error.details.type")
            == "billing"
        )
        assert (
            provider._extract_json_value(data, "response.error.details.subtype")
            == "hard_limit"
        )
        assert provider._extract_json_value(data, "response.error.details") == {
            "type": "billing",
            "subtype": "hard_limit",
        }

        # Partial path that exists but leads to non-dict
        data2 = {"a": {"b": "value"}}
        assert provider._extract_json_value(data2, "a.b.c") is None

    def test_extract_json_value_non_dict_data(self):
        """Test extraction with non-dictionary data structures."""
        provider = self.create_mock_provider()

        # Data is not a dict at some level
        data = {"error": "simple string"}
        assert provider._extract_json_value(data, "error.type") is None

        # Data is a list
        data = {"errors": [{"code": 1001}, {"code": 1002}]}
        # Lists are not supported in current implementation
        assert provider._extract_json_value(data, "errors.0.code") is None

        # Data is None - method expects Dict[str, Any], but we test edge case
        # We'll skip this test as it's not valid for the method signature
        pass

    # --- Tests for _refine_error_reason ---

    @pytest.mark.asyncio
    async def test_refine_error_reason_disabled(self):
        """Test that disabled error parsing returns default reason."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        result = await provider._refine_error_reason(
            response=mock_response, default_reason=ErrorReason.BAD_REQUEST
        )

        assert result == ErrorReason.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_refine_error_reason_no_rules_for_status(self):
        """Test that no matching rules returns default reason."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit",
                        map_to="rate_limited",
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400  # No rule for 400

        result = await provider._refine_error_reason(
            response=mock_response, default_reason=ErrorReason.BAD_REQUEST
        )

        assert result == ErrorReason.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_refine_error_reason_simple_match(self):
        """Test simple rule matching with JSON response."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Mock response body
        response_data = {"error": {"type": "Arrearage", "message": "Payment overdue"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )

        assert result == ErrorReason.INVALID_KEY

    @pytest.mark.asyncio
    async def test_refine_error_reason_priority_ordering(self):
        """Test that higher priority rules win."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="insufficient_quota",
                        map_to="no_quota",
                        priority=5,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10,  # Higher priority
                    ),
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Response matches BOTH rules (different paths)
        response_data = {"error": {"type": "Arrearage", "code": "insufficient_quota"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )

        # Should use higher priority rule (invalid_key)
        assert result == ErrorReason.INVALID_KEY

    @pytest.mark.asyncio
    async def test_refine_error_reason_regex_matching(self):
        """Test regex pattern matching in rules."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern="quota.*exceeded|limit.*reached",
                        map_to="no_quota",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Test different messages that should match
        test_cases = [
            ("Your quota has been exceeded", ErrorReason.NO_QUOTA),
            ("API limit reached for today", ErrorReason.NO_QUOTA),
            ("Daily limit reached", ErrorReason.NO_QUOTA),
            ("Some other error", ErrorReason.BAD_REQUEST),  # Should not match
        ]

        for message, expected in test_cases:
            response_data = {"error": {"message": message}}
            result = await provider._refine_error_reason(
                response=mock_response,
                default_reason=ErrorReason.BAD_REQUEST,
                response_data=response_data,
            )
            assert result == expected, f"Failed for message: {message}"

    @pytest.mark.asyncio
    async def test_refine_error_reason_case_insensitive(self):
        """Test that regex matching is case-insensitive."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="arrearage",
                        map_to="invalid_key",  # Lowercase pattern
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Response has uppercase
        response_data = {"error": {"type": "ARREARAGE"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )

        assert result == ErrorReason.INVALID_KEY

    @pytest.mark.asyncio
    async def test_refine_error_reason_map_to_validated_at_schema_level(self):
        """
        Test that map_to is validated at the Pydantic schema level,
        ensuring _refine_error_reason always receives valid ErrorReason values.

        Since map_to is now typed as ErrorReason in ErrorParsingRule,
        invalid values are rejected at construction time by Pydantic,
        not at runtime by _refine_error_reason.
        """
        # Verify that invalid map_to values are rejected by Pydantic
        with pytest.raises(ValidationError) as exc_info:
            ErrorParsingRule(
                status_code=400,
                error_path="error.type",
                match_pattern="TestError",
                map_to="invalid_error_reason",  # Not a valid ErrorReason
            )

        error_message = str(exc_info.value)
        assert "invalid_error_reason" in error_message or "map_to" in error_message

        # Verify that valid map_to values work correctly with _refine_error_reason
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        response_data = {"error": {"type": "Arrearage"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )

        # Should return the valid ErrorReason from the rule
        assert result == ErrorReason.INVALID_KEY

    @pytest.mark.asyncio
    async def test_refine_error_reason_body_parsing(self):
        """Test that response body is parsed when not provided."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = AsyncMock()
        mock_response.status_code = 400

        # Mock aread() to return JSON body
        body_json = json.dumps({"error": {"type": "Arrearage"}}).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=body_json)

        result = await provider._refine_error_reason(
            response=mock_response, default_reason=ErrorReason.BAD_REQUEST
        )

        assert result == ErrorReason.INVALID_KEY
        mock_response.aread.assert_called_once()

    @pytest.mark.asyncio
    async def test_refine_error_reason_empty_body(self):
        """Test handling of empty response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern=".*",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.aread = AsyncMock(return_value=b"")  # Empty body

        result = await provider._refine_error_reason(
            response=mock_response, default_reason=ErrorReason.BAD_REQUEST
        )

        # Should return default reason when body is empty
        assert result == ErrorReason.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_refine_error_reason_invalid_json(self):
        """Test handling of invalid JSON in response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern=".*",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.aread = AsyncMock(return_value=b"Invalid JSON {")

        result = await provider._refine_error_reason(
            response=mock_response, default_reason=ErrorReason.BAD_REQUEST
        )

        # Should return default reason when JSON is invalid
        assert result == ErrorReason.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_refine_error_reason_pre_read_body_bytes(self):
        """Test using pre-read body bytes to avoid re-reading."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Pre-read body bytes
        body_bytes = json.dumps({"error": {"type": "Arrearage"}}).encode("utf-8")

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes,
        )

        assert result == ErrorReason.INVALID_KEY
        # aread() should not be called when body_bytes is provided
        assert not hasattr(mock_response, "aread") or not mock_response.aread.called

    @pytest.mark.asyncio
    async def test_refine_error_reason_rule_evaluation_error(self):
        """Test handling of rules that don't match alongside rules that do."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.nonexistent_field",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=5,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="valid_pattern",
                        map_to=ErrorReason.NO_QUOTA,
                        priority=10,
                    ),
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        response_data = {"error": {"type": "Arrearage", "code": "valid_pattern"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )

        # First rule's path doesn't exist (no match), second rule matches
        assert result == ErrorReason.NO_QUOTA

    @pytest.mark.asyncio
    async def test_refine_error_reason_multiple_status_codes(self):
        """Test rules filtering by status code."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                    ),
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit",
                        map_to="rate_limited",
                    ),
                    ErrorParsingRule(
                        status_code=500,
                        error_path="error.message",
                        match_pattern="server_error",
                        map_to="server_error",
                    ),
                ],
            )
        )

        # Test 400 response
        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        response_data_400 = {"error": {"type": "Arrearage"}}

        result_400 = await provider._refine_error_reason(
            response=mock_response_400,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data_400,
        )
        assert result_400 == ErrorReason.INVALID_KEY

        # Test 429 response
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        response_data_429 = {"error": {"code": "rate_limit"}}

        result_429 = await provider._refine_error_reason(
            response=mock_response_429,
            default_reason=ErrorReason.RATE_LIMITED,
            response_data=response_data_429,
        )
        assert result_429 == ErrorReason.RATE_LIMITED

        # Test 500 response (no matching data, should return default)
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        response_data_500 = {"error": {"message": "different error"}}

        result_500 = await provider._refine_error_reason(
            response=mock_response_500,
            default_reason=ErrorReason.SERVER_ERROR,
            response_data=response_data_500,
        )
        assert result_500 == ErrorReason.SERVER_ERROR

    # --- BASE-1: _refine_error_reason reads ProviderConfig.error_parsing ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_reads_provider_config_error_parsing(self):
        """
        BASE-1: _refine_error_reason() reads self.config.error_parsing
        (not self.config.gateway_policy.error_parsing).

        Verifies: When error_parsing is on ProviderConfig, rules are applied.
        When accessed via gateway_policy, it does not exist there.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=10,
                    )
                ],
            )
        )

        # Verify: config.error_parsing exists at ProviderConfig level
        assert hasattr(provider.config, "error_parsing")
        assert provider.config.error_parsing.enabled is True

        # Verify: _refine_error_reason applies rules from ProviderConfig.error_parsing
        mock_response = MagicMock()
        mock_response.status_code = 400
        response_data = {"error": {"type": "Arrearage"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data,
        )
        assert result == ErrorReason.INVALID_KEY

    # --- BASE-2: fulltext mode with error_path="$" ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_mode_dollar(self):
        """
        BASE-2: Fulltext mode with error_path="$" — regex applied
        to the entire raw response body.

        Verifies: re.search("RATE_LIMIT_EXCEEDED", raw_body) matches,
        returning the mapped ErrorReason.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=429,
                        error_path="$",
                        match_pattern="RATE_LIMIT_EXCEEDED",
                        map_to=ErrorReason.RATE_LIMITED,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 429

        body_bytes = b'{"error":{"message":"RATE_LIMIT_EXCEEDED: too many requests"}}'

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.NO_QUOTA,
            body_bytes=body_bytes,
        )
        assert result == ErrorReason.RATE_LIMITED

    # --- BASE-3: fulltext mode with error_path="" ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_mode_empty_path(self):
        """
        BASE-3: Fulltext mode with error_path="" — equivalent to "$",
        regex applied to the entire raw response body.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=429,
                        error_path="",
                        match_pattern="RATE_LIMIT_EXCEEDED",
                        map_to=ErrorReason.RATE_LIMITED,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 429

        body_bytes = b'{"error":{"message":"RATE_LIMIT_EXCEEDED: too many requests"}}'

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.NO_QUOTA,
            body_bytes=body_bytes,
        )
        assert result == ErrorReason.RATE_LIMITED

    # --- BASE-4: fulltext mode — pattern not found ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_no_match(self):
        """
        BASE-4: Fulltext mode where the pattern is not found in the
        raw body. Rule is not added to matched_rules, default_reason
        is returned.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="$",
                        match_pattern="RATE_LIMIT_EXCEEDED",
                        map_to=ErrorReason.RATE_LIMITED,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        body_bytes = b'{"error":{"message":"Invalid request format"}}'

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes,
        )
        assert result == ErrorReason.BAD_REQUEST

    # --- BASE-5: fulltext mode with body_bytes=None ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_body_bytes_none(self):
        """
        BASE-5: Fulltext mode with body_bytes=None — no text available
        for search, rule is skipped, default_reason returned.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="$",
                        match_pattern="RATE_LIMIT_EXCEEDED",
                        map_to=ErrorReason.RATE_LIMITED,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=None,
        )
        assert result == ErrorReason.BAD_REQUEST

    # --- BASE-6: fulltext mode with non-UTF-8 body ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_non_utf8_body(self):
        """
        BASE-6: Fulltext mode with non-UTF-8 body_bytes — decoded
        with errors="ignore", regex applied to recovered text.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="$",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=10,
                    )
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        # Mix valid UTF-8 text with invalid bytes (0xff 0xfe)
        body_bytes = b'\xff\xfe{"error":{"type":"Arrearage"}}\xff\xfe'

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes,
        )
        # After decoding with errors="ignore", the invalid bytes are dropped,
        # but "Arrearage" is still present in the recovered text
        assert result == ErrorReason.INVALID_KEY

    # --- BASE-7: fulltext + dotpath coexist, fulltext wins by priority ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_fulltext_and_dotpath_coexist_priority(self):
        """
        BASE-7: Fulltext rule (priority=80) and dot-path rule (priority=50)
        for the same status_code. Both match, but fulltext wins because
        it has higher priority.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="$",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=80,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.NO_QUOTA,
                        priority=50,
                    ),
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        body_bytes = b'{"error":{"type":"Arrearage","message":"Payment overdue"}}'
        response_data = {"error": {"type": "Arrearage", "message": "Payment overdue"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes,
            response_data=response_data,
        )
        # Fulltext rule wins (priority 80 > 50)
        assert result == ErrorReason.INVALID_KEY

    # --- BASE-8: dotpath wins over fulltext by priority ---
    @pytest.mark.asyncio
    async def test_refine_error_reason_dotpath_wins_over_fulltext_priority(self):
        """
        BASE-8: Dot-path rule (priority=100) and fulltext rule (priority=10)
        for the same status_code. Both match, but dotpath wins because
        it has higher priority.
        """
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.NO_QUOTA,
                        priority=100,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="$",
                        match_pattern="Arrearage",
                        map_to=ErrorReason.INVALID_KEY,
                        priority=10,
                    ),
                ],
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        body_bytes = b'{"error":{"type":"Arrearage","message":"Payment overdue"}}'
        response_data = {"error": {"type": "Arrearage", "message": "Payment overdue"}}

        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes,
            response_data=response_data,
        )
        # Dot-path rule wins (priority 100 > 10)
        assert result == ErrorReason.NO_QUOTA


class TestSendProxyRequest400BodyPreservation:
    """
    Test suite for the preserve-400-error-body change in _send_proxy_request.

    Verifies that for HTTP 400 in the Zero-Overhead Fallback branch,
    the upstream stream is NOT closed (so the gateway can read the body
    via aread() and return the original provider error to the client).
    All other status codes keep the existing behavior (stream closed).
    """

    def _create_provider_with_config(
        self,
        debug_mode: str = "disabled",
        error_parsing_enabled: bool = False,
        error_parsing_rules: list | None = None,
    ) -> MockAIBaseProvider:
        """Helper to create a MockAIBaseProvider with specific config."""
        if error_parsing_rules is None:
            error_parsing_rules = []

        gateway_policy = GatewayPolicyConfig(
            debug_mode=debug_mode,
        )

        # Build a minimal ProviderConfig. error_parsing is now at the
        # ProviderConfig level (not inside gateway_policy).
        provider_config = ProviderConfig(
            provider_type="openai_like",
            keys_path="/tmp/nonexistent",
            gateway_policy=gateway_policy,
            error_parsing=ErrorParsingConfig(
                enabled=error_parsing_enabled, rules=error_parsing_rules
            ),
        )

        return MockAIBaseProvider("test_provider", provider_config)

    def _create_mock_upstream_response(
        self, status_code: int, body: bytes = b'{"error":"test"}'
    ) -> AsyncMock:
        """Helper to create a mock httpx.Response with async methods."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = status_code
        mock_response.is_success = status_code < 400
        mock_response.aread = AsyncMock(return_value=body)
        mock_response.aclose = AsyncMock()
        return mock_response

    # --- UT-1: 400 without rules — stream NOT closed ---
    @pytest.mark.asyncio
    async def test_400_without_rules_stream_not_closed(self):
        """
        UT-1: _send_proxy_request with 400,
        no debug_mode, no error_parsing.

        Verifies: aclose() is NOT called, _parse_proxy_error is called
        with content=None, CheckResult.fail(BAD_REQUEST) is returned
        with an open stream.
        """
        provider = self._create_provider_with_config()

        mock_upstream = self._create_mock_upstream_response(status_code=400)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        # Patch _parse_proxy_error to track its call and return BAD_REQUEST
        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.BAD_REQUEST)),
        ) as mock_parse:
            response, check_result = await provider._send_proxy_request(
                mock_client, mock_request
            )

            # Verify: aclose() was NOT called (stream preserved for 400)
            mock_upstream.aclose.assert_not_called()

            # Verify: _parse_proxy_error was called with content=None
            mock_parse.assert_called_once_with(mock_upstream, None)

            # Verify: CheckResult is fail with BAD_REQUEST
            assert check_result.available is False
            assert check_result.error_reason == ErrorReason.BAD_REQUEST

            # Verify: the response stream is still open (aread would work)
            # The mock's aread hasn't been consumed by _send_proxy_request
            mock_upstream.aread.assert_not_called()

    # --- UT-2: 401 without rules — stream closed (regression) ---
    @pytest.mark.asyncio
    async def test_401_without_rules_stream_closed_regression(self):
        """
        UT-2: _send_proxy_request with 401,
        no debug_mode, no error_parsing.

        Verifies: aclose() IS called (existing Zero-Overhead Fallback
        behavior unchanged for non-400 codes).
        """
        provider = self._create_provider_with_config()

        mock_upstream = self._create_mock_upstream_response(status_code=401)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.INVALID_KEY)),
        ) as mock_parse:
            response, check_result = await provider._send_proxy_request(
                mock_client, mock_request
            )

            # Verify: aclose() WAS called (stream closed for 401)
            mock_upstream.aclose.assert_called_once()

            # Verify: _parse_proxy_error was called with content=None
            mock_parse.assert_called_once_with(mock_upstream, None)

    # --- UT-4: 400 + error_parsing — body read, error_parsing priority ---
    @pytest.mark.asyncio
    async def test_400_with_error_parsing_body_read_priority(self):
        """
        UT-4: _send_proxy_request with 400, error_parsing.enabled = true,
        rule exists for 400.

        Verifies: aread() IS called (error_parsing has priority),
        _refine_error_reason is called with body content,
        _parse_proxy_error receives content_bytes, stream is consumed.
        """
        provider = self._create_provider_with_config(
            error_parsing_enabled=True,
            error_parsing_rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="Arrearage",
                    map_to="invalid_key",
                    priority=10,
                )
            ],
        )

        body = b'{"error":{"type":"Arrearage"}}'
        mock_upstream = self._create_mock_upstream_response(status_code=400, body=body)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        # Patch _parse_proxy_error to track its call and return a result
        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.INVALID_KEY)),
        ) as mock_parse:
            response, check_result = await provider._send_proxy_request(
                mock_client, mock_request
            )

            # Verify: aread() WAS called (error_parsing reads body)
            mock_upstream.aread.assert_called_once()

            # Verify: _parse_proxy_error was called with content_bytes (not None)
            call_args = mock_parse.call_args
            assert (
                call_args[0][1] is not None
            ), "Expected content_bytes to be passed to _parse_proxy_error, got None"

            # Verify: the content_bytes match the body
            assert call_args[0][1] == body

    # --- UT-5: 400 + debug_mode — body read, debug priority ---
    @pytest.mark.asyncio
    async def test_400_with_debug_mode_body_read_priority(self):
        """
        UT-5: _send_proxy_request with 400, debug_mode = "full_body".

        Verifies: aread() IS called (debug mode has priority over
        Zero-Overhead Fallback), body read for logging.
        """
        provider = self._create_provider_with_config(debug_mode="full_body")

        body = b'{"error":{"message":"Invalid model"}}'
        mock_upstream = self._create_mock_upstream_response(status_code=400, body=body)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.BAD_REQUEST)),
        ) as mock_parse:
            response, check_result = await provider._send_proxy_request(
                mock_client, mock_request
            )

            # Verify: aread() WAS called (debug mode reads body)
            mock_upstream.aread.assert_called_once()

            # Verify: _parse_proxy_error was called with content_bytes
            call_args = mock_parse.call_args
            assert call_args[0][1] == body

    # --- UT-6: 500 without rules — stream closed (regression) ---
    @pytest.mark.asyncio
    async def test_500_without_rules_stream_closed_regression(self):
        """
        UT-6: _send_proxy_request with 500,
        no debug_mode, no error_parsing.

        Verifies: aclose() IS called (existing behavior for 5xx unchanged).
        """
        provider = self._create_provider_with_config()

        mock_upstream = self._create_mock_upstream_response(status_code=500)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.SERVER_ERROR)),
        ) as mock_parse:
            response, check_result = await provider._send_proxy_request(
                mock_client, mock_request
            )

            # Verify: aclose() WAS called (stream closed for 500)
            mock_upstream.aclose.assert_called_once()

            # Verify: _parse_proxy_error was called with content=None
            mock_parse.assert_called_once_with(mock_upstream, None)

    # --- BASE-10: _send_proxy_request has no fast_status_mapping branch ---
    @pytest.mark.asyncio
    async def test_send_proxy_request_no_fast_status_mapping(self):
        """
        BASE-10: _send_proxy_request does not reference fast_status_mapping.
        The priority order is: debug_mode > error_parsing > fallback.

        Verifies: With error_parsing enabled for 400, body is read
        (error_parsing branch). Without error_parsing or debug_mode,
        fallback branch is used (no body read, stream preserved for 400).
        """
        # Test with error_parsing enabled — body is read
        provider_with_parsing = self._create_provider_with_config(
            error_parsing_enabled=True,
            error_parsing_rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="Arrearage",
                    map_to=ErrorReason.INVALID_KEY,
                    priority=10,
                )
            ],
        )

        body = b'{"error":{"type":"Arrearage"}}'
        mock_upstream = self._create_mock_upstream_response(status_code=400, body=body)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        with patch.object(
            provider_with_parsing,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.INVALID_KEY)),
        ):
            _, result = await provider_with_parsing._send_proxy_request(
                mock_client, mock_request
            )
            # Body was read (error_parsing branch)
            mock_upstream.aread.assert_called_once()
            assert result.error_reason == ErrorReason.INVALID_KEY

        # Test without error_parsing or debug_mode — fallback branch
        provider_fallback = self._create_provider_with_config()

        mock_upstream2 = self._create_mock_upstream_response(status_code=400)
        mock_client2 = AsyncMock(spec=httpx.AsyncClient)
        mock_client2.send = AsyncMock(return_value=mock_upstream2)

        with patch.object(
            provider_fallback,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.BAD_REQUEST)),
        ):
            _, result2 = await provider_fallback._send_proxy_request(
                mock_client2, mock_request
            )
            # Body was NOT read (fallback branch)
            mock_upstream2.aread.assert_not_called()
            assert result2.error_reason == ErrorReason.BAD_REQUEST

    # --- BASE-11: _send_proxy_request reads ProviderConfig.error_parsing ---
    @pytest.mark.asyncio
    async def test_send_proxy_request_reads_provider_error_parsing(self):
        """
        BASE-11: _send_proxy_request reads self.config.error_parsing
        for gating body read (not self.config.gateway_policy.error_parsing).

        Verifies: should_read_body is computed from ProviderConfig.error_parsing.
        """
        provider = self._create_provider_with_config(
            error_parsing_enabled=True,
            error_parsing_rules=[
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.type",
                    match_pattern="Arrearage",
                    map_to=ErrorReason.INVALID_KEY,
                    priority=10,
                )
            ],
        )

        # Verify: config.error_parsing is at ProviderConfig level
        assert hasattr(provider.config, "error_parsing")
        assert provider.config.error_parsing.enabled is True
        assert len(provider.config.error_parsing.rules) == 1

        body = b'{"error":{"type":"Arrearage"}}'
        mock_upstream = self._create_mock_upstream_response(status_code=400, body=body)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.send = AsyncMock(return_value=mock_upstream)
        mock_request = MagicMock(spec=httpx.Request)

        with patch.object(
            provider,
            "_parse_proxy_error",
            new=AsyncMock(return_value=CheckResult.fail(ErrorReason.INVALID_KEY)),
        ):
            _, result = await provider._send_proxy_request(mock_client, mock_request)
            # Body was read because error_parsing.enabled=True and rule matches 400
            mock_upstream.aread.assert_called_once()
            assert result.error_reason == ErrorReason.INVALID_KEY


class TestCheckFastFailRemoved:
    """Test suite verifying _check_fast_fail method has been removed."""

    # --- BASE-9: _check_fast_fail method does not exist ---
    def test_check_fast_fail_method_removed(self):
        """
        BASE-9: _check_fast_fail method does not exist on AIBaseProvider.

        Verifies: hasattr(provider, "_check_fast_fail") == False.
        """
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.error_parsing = ErrorParsingConfig(enabled=False, rules=[])
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)

        provider = MockAIBaseProvider("test_provider", mock_config)

        assert not hasattr(
            provider, "_check_fast_fail"
        ), "_check_fast_fail should not exist on AIBaseProvider"
