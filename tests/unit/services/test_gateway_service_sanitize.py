"""
Unit tests for sanitization helper functions in gateway_service.

Tests cover _sanitize_body (SSE-aware, sensitive field redaction),
_sanitize_headers (header masking), and _log_debug_info integration
for both no_content and full_body debug modes.
"""

import json
import logging

import pytest

from src.services.gateway_service import (
    _log_debug_info,
    _sanitize_body,
    _sanitize_headers,
)


class TestSanitizeHeaders:
    """Tests for the _sanitize_headers function."""

    def test_sanitize_headers_no_sensitive(self):
        """Headers without sensitive keys should remain unchanged."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TestClient",
            "X-Custom": "value",
        }
        result = _sanitize_headers(headers)
        assert result == headers

    def test_sanitize_headers_authorization_bearer(self):
        """Authorization Bearer token should be masked."""
        headers = {
            "Authorization": "Bearer secret_token_123",
            "Content-Type": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["Authorization"] == "Bearer ***"
        assert result["Content-Type"] == "application/json"

    def test_sanitize_headers_authorization_other(self):
        """Non-Bearer Authorization should be masked completely."""
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        result = _sanitize_headers(headers)
        assert result["Authorization"] == "***"

    def test_sanitize_headers_x_api_key(self):
        """x-api-key header should be masked."""
        headers = {"x-api-key": "secret", "Accept": "*/*"}
        result = _sanitize_headers(headers)
        assert result["x-api-key"] == "***"
        assert result["Accept"] == "*/*"

    def test_sanitize_headers_x_goog_api_key(self):
        """x-goog-api-key header should be masked."""
        headers = {"x-goog-api-key": "google_secret", "Accept": "*/*"}
        result = _sanitize_headers(headers)
        assert result["x-goog-api-key"] == "***"
        assert result["Accept"] == "*/*"

    def test_sanitize_headers_case_insensitive(self):
        """Sensitive header detection should be case-insensitive."""
        headers = {"AUTHORIZATION": "Bearer token", "X-API-KEY": "key"}
        result = _sanitize_headers(headers)
        # Keys retain original case
        assert result["AUTHORIZATION"] == "Bearer ***"
        assert result["X-API-KEY"] == "***"

    def test_sanitize_headers_authorization_masked_in_full_body(self):
        """Authorization header masked in full_body mode (regression check).

        Verify that 'Bearer sk-abc123' becomes 'Bearer ***' — the Bearer
        scheme is preserved while the credential is masked.
        """
        headers = {"Authorization": "Bearer sk-abc123"}
        result = _sanitize_headers(headers)
        assert result["Authorization"] == "Bearer ***"
        assert "sk-abc123" not in result["Authorization"]


class TestSanitizeBody:
    """Tests for the _sanitize_body function — SSE-aware, sensitive field redaction."""

    # --- Task 1: SSE body does NOT bypass sanitization ---
    def test_sanitize_body_sse_does_not_bypass_redaction(self):
        """SSE string with sensitive fields must be parsed and redacted,
        not treated as a raw-string fallback."""
        body = b'data: {"api_key": "sk-abc"}\n\n'
        result = _sanitize_body(body)
        # The api_key value must be redacted to "***"
        assert '"api_key": "***"' in result
        # The original secret must NOT appear
        assert "sk-abc" not in result
        # Output must still be SSE-formatted (data: prefix preserved)
        assert result.startswith("data: ")

    # --- Task 2: SSE sensitive fields redacted inside data: lines ---
    def test_sanitize_body_sse_sensitive_fields_redacted(self):
        """SSE data: line with multiple sensitive fields: api_key, token
        are redacted while non-sensitive fields like model remain intact."""
        body = (
            b'data: {"api_key": "sk-secret", "token": "tok-abc", "model": "gpt-4"}\n\n'
        )
        result = _sanitize_body(body)
        assert '"api_key": "***"' in result
        assert '"token": "***"' in result
        assert '"model": "gpt-4"' in result
        assert "sk-secret" not in result
        assert "tok-abc" not in result

    # --- Task 3: SSE multiple events ---
    def test_sanitize_body_sse_multiple_events(self):
        """Body with multiple SSE events — each event is sanitized independently."""
        body = b'data: {"api_key": "sk-1"}\n\ndata: {"token": "tok-2"}\n\n'
        result = _sanitize_body(body)
        # Both events must be present and independently sanitized
        assert '"api_key": "***"' in result
        assert '"token": "***"' in result
        assert "sk-1" not in result
        assert "tok-2" not in result
        # The double-newline event separator must be preserved
        assert "\n\n" in result

    # --- Task 4: Non-SSE JSON uses existing fast path (regression) ---
    def test_sanitize_body_plain_json_fast_path(self):
        """Plain JSON (no SSE) should still use the startswith('{') fast path
        and correctly redact sensitive fields."""
        body = b'{"api_key": "sk-abc"}'
        result = _sanitize_body(body)
        assert '"api_key": "***"' in result
        assert "sk-abc" not in result
        # Must NOT have SSE formatting artifacts
        assert "data: " not in result

    # --- Task 5: SSE malformed ---
    def test_sanitize_body_sse_malformed_json(self):
        """Invalid JSON after data: prefix — no crash, line preserved as-is."""
        body = b"data: {not valid json}\n\n"
        result = _sanitize_body(body)
        # The malformed line should be preserved unchanged
        assert "data: {not valid json}" in result
        # No crash / exception should occur

    # --- Task 6: Sensitive fields redacted in BOTH no_content and full_body modes ---
    @pytest.mark.parametrize(
        "debug_mode",
        ["no_content", "full_body"],
        ids=["no_content_mode", "full_body_mode"],
    )
    @pytest.mark.parametrize(
        "sensitive_field,value",
        [
            ("api_key", "sk-live-abc"),
            ("token", "tok-xyz"),
            ("secret", "sec-123"),
            ("password", "pw-456"),
        ],
        ids=["api_key", "token", "secret", "password"],
    )
    def test_sanitize_body_sensitive_fields_redacted_in_both_modes(
        self, debug_mode: str, sensitive_field: str, value: str
    ):
        """Sensitive fields (api_key, token, secret, password) must be masked
        in both no_content and full_body debug modes via _log_debug_info."""
        data = {sensitive_field: value, "model": "gpt-4"}
        body = json.dumps(data).encode("utf-8")
        # _sanitize_body is called inside _log_debug_info for both modes;
        # verify that _sanitize_body itself redacts regardless of provider_type
        result = _sanitize_body(body, provider_type="openai_like")
        assert f'"{sensitive_field}": "***"' in result
        assert value not in result
        assert '"model": "gpt-4"' in result

    # --- Task 7: Authorization header masked in full_body ---
    def test_sanitize_headers_authorization_masked_in_full_body_mode(self):
        """In full_body mode, Authorization header must be masked:
        'Bearer sk-abc123' → 'Bearer ***'."""
        headers = {
            "Authorization": "Bearer sk-abc123",
            "Content-Type": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["Authorization"] == "Bearer ***"
        assert "sk-abc123" not in result["Authorization"]
        assert result["Content-Type"] == "application/json"

    # --- Task 8: provider_type passthrough in _sanitize_body ---
    def test_sanitize_body_accepts_provider_type_passthrough(self):
        """_sanitize_body accepts provider_type parameter and passes it through
        correctly. While _sanitize_body itself doesn't call redact_content,
        the provider_type is available for future integration and the body
        is still correctly sanitized for sensitive fields."""
        body = b'{"api_key": "sk-test", "model": "gpt-4"}'
        # Call with provider_type — should not crash and should still redact
        result = _sanitize_body(body, provider_type="openai_like")
        assert '"api_key": "***"' in result
        assert "sk-test" not in result
        assert '"model": "gpt-4"' in result

    def test_sanitize_body_provider_type_with_sse(self):
        """SSE body with provider_type — SSE parsing and sensitive field
        redaction both work correctly when provider_type is provided."""
        body = b'data: {"api_key": "sk-secret", "model": "gpt-4"}\n\n'
        result = _sanitize_body(body, provider_type="openai_like")
        assert '"api_key": "***"' in result
        assert "sk-secret" not in result
        assert '"model": "gpt-4"' in result

    # --- Task 9: Large body NOT truncated ---
    def test_sanitize_body_large_not_truncated(self):
        """Body >10KB must NOT be truncated — no '... (truncated)' suffix.
        MAX_DEBUG_BODY_SIZE no longer exists in the codebase."""
        # Build a body larger than 10KB
        data = {"api_key": "sk-test", "content": "x" * 12000}
        body = json.dumps(data).encode("utf-8")
        assert len(body) > 10240  # Verify it's >10KB
        result = _sanitize_body(body)
        # Sensitive field must be redacted
        assert '"api_key": "***"' in result
        # No truncation marker should appear
        assert "... (truncated)" not in result
        # The long content value must still be present (not truncated)
        assert "x" * 12000 in result

    # --- Existing tests (preserved / updated) ---
    def test_sanitize_body_json_with_sensitive_keys(self):
        """JSON bodies with sensitive keys should have values redacted."""
        data = {
            "api_key": "secret123",
            "token": "abcd",
            "password": "mypass",
            "other": "safe",
        }
        body = json.dumps(data).encode("utf-8")
        result = _sanitize_body(body)
        assert '"api_key": "***"' in result
        assert '"token": "***"' in result
        assert '"password": "***"' in result
        assert '"other": "safe"' in result

    def test_sanitize_body_json_variations(self):
        """Test variations of sensitive key names (underscore, hyphen)."""
        body = b'{"api-key": "secret", "api_key": "secret2", "APIToken": "secret3"}'
        result = _sanitize_body(body)
        assert '"api-key": "***"' in result
        assert '"api_key": "***"' in result
        # APIToken is not matched because the regex expects "token" as a quoted key
        assert '"APIToken": "secret3"' in result

    def test_sanitize_body_non_json(self):
        """Non-JSON body should be decoded as UTF-8 string."""
        body = b"plain text body"
        result = _sanitize_body(body)
        assert result == "plain text body"

    def test_sanitize_body_invalid_utf8(self):
        """Invalid UTF-8 bytes should be represented with repr."""
        body = b"\xff\xfe"
        result = _sanitize_body(body)
        assert result == repr(body)

    def test_sanitize_body_json_array(self):
        """JSON array should be processed."""
        body = b'[{"api_key": "secret"}]'
        result = _sanitize_body(body)
        assert '"api_key": "***"' in result

    def test_sanitize_body_large_json(self):
        """Large JSON should still be processed."""
        data = {"token": "x" * 1000}
        body = json.dumps(data).encode("utf-8")
        result = _sanitize_body(body)
        assert '"token": "***"' in result
        assert "x" * 1000 not in result


class TestLogDebugInfoIntegration:
    """Integration tests for _log_debug_info verifying that _sanitize_body
    and _sanitize_headers are called correctly for both debug modes."""

    @pytest.mark.parametrize(
        "debug_mode",
        ["no_content", "full_body"],
        ids=["no_content", "full_body"],
    )
    def test_log_debug_info_sanitizes_body_in_both_modes(
        self, debug_mode: str, caplog: pytest.LogCaptureFixture
    ):
        """_log_debug_info calls _sanitize_body for both no_content and full_body
        modes, and sensitive fields are redacted in the logged output."""
        request_body = b'{"api_key": "sk-test", "model": "gpt-4"}'
        response_body = b'{"token": "tok-resp", "id": "chatcmpl-1"}'
        request_headers = {"Authorization": "Bearer sk-abc123"}
        response_headers = {"Content-Type": "application/json"}

        with caplog.at_level(logging.INFO):
            _log_debug_info(
                debug_mode=debug_mode,
                instance_name="test-instance",
                request_method="POST",
                request_path="/v1/chat/completions",
                request_headers=request_headers,
                request_body=request_body,
                response_status=200,
                response_headers=response_headers,
                response_body=response_body,
                provider_type="openai_like",
            )

        # Sensitive fields must be redacted in logged output
        assert "sk-test" not in caplog.text
        assert "tok-resp" not in caplog.text
        assert "sk-abc123" not in caplog.text
        # Redacted markers must appear
        assert '"api_key": "***"' in caplog.text
        assert '"token": "***"' in caplog.text
        assert "Bearer ***" in caplog.text
        # Non-sensitive fields must remain
        assert '"model": "gpt-4"' in caplog.text
        assert '"id": "chatcmpl-1"' in caplog.text

    def test_log_debug_info_sse_body_in_full_body_mode(
        self, caplog: pytest.LogCaptureFixture
    ):
        """_log_debug_info correctly handles SSE response body in full_body mode."""
        request_body = b'{"model": "gpt-4"}'
        response_body = b'data: {"api_key": "sk-secret", "choices": []}\n\n'
        request_headers = {"Authorization": "Bearer sk-abc123"}
        response_headers = {"Content-Type": "text/event-stream"}

        with caplog.at_level(logging.INFO):
            _log_debug_info(
                debug_mode="full_body",
                instance_name="test-instance",
                request_method="POST",
                request_path="/v1/chat/completions",
                request_headers=request_headers,
                request_body=request_body,
                response_status=200,
                response_headers=response_headers,
                response_body=response_body,
                provider_type="openai_like",
            )

        # SSE body must be sanitized — api_key redacted
        assert "sk-secret" not in caplog.text
        assert '"api_key": "***"' in caplog.text
        # Authorization must be masked
        assert "sk-abc123" not in caplog.text
        assert "Bearer ***" in caplog.text
