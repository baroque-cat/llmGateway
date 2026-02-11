"""
Unit tests for sanitization helper functions in gateway_service.
"""

import json

import pytest

from src.services.gateway_service import _sanitize_headers, _sanitize_body


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


class TestSanitizeBody:
    """Tests for the _sanitize_body function."""

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
        # Should be a string with redacted values
        assert '"api_key": "***"' in result
        assert '"token": "***"' in result
        assert '"password": "***"' in result
        assert '"other": "safe"' in result

    def test_sanitize_body_json_variations(self):
        """Test variations of sensitive key names (underscore, hyphen)."""
        body = b'{"api-key": "secret", "api_key": "secret2", "APIToken": "secret3"}'
        result = _sanitize_body(body)
        # Should redact api-key and api_key (matched by regex)
        assert '"api-key": "***"' in result
        assert '"api_key": "***"' in result
        # APIToken is not matched because the regex expects "token" as a quoted key
        # (case-insensitive but whole word). The value should remain unchanged.
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
        # repr of bytes includes b'...'
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
