"""
Unit tests for content redaction in sanitize_content module.

Tests cover REDACT_CONTENT_PATHS structure, provider-specific redaction
(OpenAI-like, Gemini, Anthropic), wildcard/nested path traversal,
edge cases (path not found, malformed SSE, unknown provider), and
content-only redaction scope.
"""

import json

from src.services.sanitize_content import (
    REDACT_CONTENT_PATHS,
    _redact_json,
    redact_content,
)


class TestRedactContentPathsStructure:
    """Task 1: Verify REDACT_CONTENT_PATHS dict structure."""

    def test_has_all_provider_keys(self):
        """REDACT_CONTENT_PATHS must contain openai_like, gemini, anthropic."""
        assert set(REDACT_CONTENT_PATHS.keys()) == {
            "openai_like",
            "gemini",
            "anthropic",
        }

    def test_each_provider_has_request_and_response(self):
        """Each provider must have both 'request' and 'response' keys."""
        for provider in REDACT_CONTENT_PATHS:
            assert "request" in REDACT_CONTENT_PATHS[provider]
            assert "response" in REDACT_CONTENT_PATHS[provider]

    def test_total_path_count_is_19(self):
        """Total number of paths across all providers should be 19."""
        total = 0
        for provider in REDACT_CONTENT_PATHS:
            for direction in ("request", "response"):
                total += len(REDACT_CONTENT_PATHS[provider][direction])
        assert total == 19

    def test_openai_like_request_paths(self):
        """OpenAI-like request paths must include messages.*.content and variants."""
        paths = REDACT_CONTENT_PATHS["openai_like"]["request"]
        assert "messages.*.content" in paths
        assert "messages.*.content.*.text" in paths
        assert "messages.*.content.*.image_url" in paths

    def test_openai_like_response_paths(self):
        """OpenAI-like response paths must include choices.* variants."""
        paths = REDACT_CONTENT_PATHS["openai_like"]["response"]
        assert "choices.*.message.content" in paths
        assert "choices.*.delta.content" in paths
        assert "choices.*.delta.reasoning_content" in paths

    def test_gemini_request_paths(self):
        """Gemini request paths must include contents and systemInstruction."""
        paths = REDACT_CONTENT_PATHS["gemini"]["request"]
        assert "contents.*.parts.*.text" in paths
        assert "systemInstruction.parts.*.text" in paths

    def test_gemini_response_paths(self):
        """Gemini response paths must include candidates.*.content.parts.*.text."""
        paths = REDACT_CONTENT_PATHS["gemini"]["response"]
        assert "candidates.*.content.parts.*.text" in paths

    def test_anthropic_request_paths(self):
        """Anthropic request paths must include messages, content, and system."""
        paths = REDACT_CONTENT_PATHS["anthropic"]["request"]
        assert "messages.*.content" in paths
        assert "messages.*.content.*.text" in paths
        assert "system" in paths

    def test_anthropic_response_paths(self):
        """Anthropic response paths must include content, content_block, and delta."""
        paths = REDACT_CONTENT_PATHS["anthropic"]["response"]
        assert "content.*.text" in paths
        assert "content.*.thinking" in paths
        assert "content.*.data" in paths
        assert "content_block.text" in paths
        assert "content_block.thinking" in paths
        assert "delta.text" in paths
        assert "delta.thinking" in paths


class TestOpenAILikeRequestRedaction:
    """Task 2: OpenAI-like request body redaction."""

    def test_messages_content_redacted(self):
        """messages[].content string values should be replaced by '***'."""
        body = json.dumps(
            {
                "model": "gpt-4",
                "temperature": 0.7,
                "messages": [
                    {"role": "user", "content": "Hello, how are you?"},
                    {"role": "assistant", "content": "I'm doing well!"},
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["messages"][0]["content"] == "***"
        assert result["messages"][1]["content"] == "***"

    def test_model_temperature_preserved(self):
        """model and temperature should remain unchanged."""
        body = json.dumps(
            {
                "model": "gpt-4",
                "temperature": 0.7,
                "messages": [
                    {"role": "user", "content": "Hello"},
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["model"] == "gpt-4"
        assert result["temperature"] == 0.7

    def test_messages_role_preserved(self):
        """messages[].role should remain unchanged."""
        body = json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi"},
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"


class TestOpenAILikeResponseRedaction:
    """Task 3: OpenAI-like response body redaction."""

    def test_choices_message_content_redacted(self):
        """choices[].message.content should be redacted."""
        body = json.dumps(
            {
                "id": "chatcmpl-123",
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Response text"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["choices"][0]["message"]["content"] == "***"

    def test_choices_delta_content_redacted(self):
        """choices[].delta.content should be redacted."""
        body = json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "streaming text"},
                        "finish_reason": None,
                    },
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["choices"][0]["delta"]["content"] == "***"

    def test_choices_delta_reasoning_content_redacted(self):
        """choices[].delta.reasoning_content should be redacted."""
        body = json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"reasoning_content": "internal reasoning"},
                        "finish_reason": None,
                    },
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["choices"][0]["delta"]["reasoning_content"] == "***"

    def test_id_model_index_finish_reason_usage_preserved(self):
        """id, model, index, finish_reason, usage should be preserved."""
        body = json.dumps(
            {
                "id": "chatcmpl-123",
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "text"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["id"] == "chatcmpl-123"
        assert result["model"] == "gpt-4"
        assert result["choices"][0]["index"] == 0
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["choices"][0]["message"]["role"] == "assistant"
        assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 20}


class TestDeepSeekReasoningContent:
    """Task 4: DeepSeek reasoning_content redaction (uses openai_like provider)."""

    def test_reasoning_content_redacted(self):
        """choices[0].delta.reasoning_content should be redacted to '***'."""
        body = json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"reasoning_content": "internal reasoning"},
                        "finish_reason": None,
                    },
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        assert result["choices"][0]["delta"]["reasoning_content"] == "***"


class TestGeminiRequestRedaction:
    """Task 5: Gemini request body redaction."""

    def test_contents_parts_text_redacted(self):
        """contents[].parts[].text should be redacted."""
        body = json.dumps(
            {
                "contents": [
                    {"role": "user", "parts": [{"text": "Hello"}, {"text": "World"}]},
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["contents"][0]["parts"][0]["text"] == "***"
        assert result["contents"][0]["parts"][1]["text"] == "***"

    def test_system_instruction_parts_text_redacted(self):
        """systemInstruction.parts[].text should be redacted."""
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": "You are helpful"}]},
                "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["systemInstruction"]["parts"][0]["text"] == "***"

    def test_generation_config_preserved(self):
        """generationConfig should remain unchanged."""
        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 100},
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["generationConfig"] == {
            "temperature": 0.5,
            "maxOutputTokens": 100,
        }

    def test_contents_role_preserved(self):
        """contents[].role should remain unchanged."""
        body = json.dumps(
            {
                "contents": [
                    {"role": "user", "parts": [{"text": "Hello"}]},
                    {"role": "model", "parts": [{"text": "Response"}]},
                ],
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["contents"][0]["role"] == "user"
        assert result["contents"][1]["role"] == "model"


class TestGeminiResponseRedaction:
    """Task 6: Gemini response body redaction."""

    def test_candidates_content_parts_text_redacted_without_thought(self):
        """candidates[].content.parts[].text should be redacted (no thought flag)."""
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Response text"}],
                        },
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["candidates"][0]["content"]["parts"][0]["text"] == "***"

    def test_candidates_content_parts_text_redacted_with_thought_true(self):
        """candidates[].content.parts[].text should be redacted even when thought=true."""
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Internal thinking", "thought": True}],
                        },
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 10},
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["candidates"][0]["content"]["parts"][0]["text"] == "***"
        # thought flag should be preserved
        assert result["candidates"][0]["content"]["parts"][0]["thought"] is True

    def test_finish_reason_role_usage_metadata_preserved(self):
        """finishReason, role, usageMetadata should be preserved."""
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "Response"}]},
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "gemini"))
        assert result["candidates"][0]["finishReason"] == "STOP"
        assert result["candidates"][0]["content"]["role"] == "model"
        assert result["usageMetadata"] == {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
        }


class TestAnthropicSSERedaction:
    """Task 7: Anthropic SSE streaming redaction."""

    def test_delta_text_redacted_for_text_delta_type(self):
        """delta.text should be redacted when type is text_delta in SSE event."""
        sse_body = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n'
        result = redact_content(sse_body.encode(), "anthropic")
        result_str = result.decode()
        # Extract the JSON after "data: "
        data_json = result_str.split("data: ")[1].strip()
        result_obj = json.loads(data_json)
        assert result_obj["delta"]["text"] == "***"

    def test_delta_thinking_redacted_for_thinking_delta_type(self):
        """delta.thinking should be redacted when type is thinking_delta in SSE event."""
        sse_body = 'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Deep thoughts"}}\n\n'
        result = redact_content(sse_body.encode(), "anthropic")
        result_str = result.decode()
        data_json = result_str.split("data: ")[1].strip()
        result_obj = json.loads(data_json)
        assert result_obj["delta"]["thinking"] == "***"

    def test_sse_type_fields_preserved(self):
        """The 'type' fields in SSE events should be preserved."""
        sse_body = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n'
        result = redact_content(sse_body.encode(), "anthropic")
        result_str = result.decode()
        data_json = result_str.split("data: ")[1].strip()
        result_obj = json.loads(data_json)
        assert result_obj["type"] == "content_block_delta"
        assert result_obj["delta"]["type"] == "text_delta"


class TestAnthropicNonStreamingRedaction:
    """Task 8: Anthropic non-streaming response redaction."""

    def test_content_text_redacted(self):
        """content[].text should be redacted."""
        body = json.dumps(
            {
                "content": [{"type": "text", "text": "Hello world"}],
                "model": "claude-3",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "anthropic"))
        assert result["content"][0]["text"] == "***"

    def test_content_thinking_redacted(self):
        """content[].thinking should be redacted."""
        body = json.dumps(
            {
                "content": [{"type": "thinking", "thinking": "Internal reasoning"}],
                "model": "claude-3",
            }
        ).encode()
        result = json.loads(redact_content(body, "anthropic"))
        assert result["content"][0]["thinking"] == "***"

    def test_content_data_redacted(self):
        """content[].data should be redacted (for tool_use blocks)."""
        body = json.dumps(
            {
                "content": [{"type": "tool_use", "data": "sensitive tool data"}],
                "model": "claude-3",
            }
        ).encode()
        result = json.loads(redact_content(body, "anthropic"))
        assert result["content"][0]["data"] == "***"

    def test_content_type_model_stop_reason_usage_preserved(self):
        """content[].type, model, stop_reason, usage should be preserved."""
        body = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "thinking", "thinking": "reasons"},
                ],
                "model": "claude-3",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        ).encode()
        result = json.loads(redact_content(body, "anthropic"))
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "thinking"
        assert result["model"] == "claude-3"
        assert result["stop_reason"] == "end_turn"
        assert result["usage"] == {"input_tokens": 10, "output_tokens": 20}


class TestWildcardPathTraversal:
    """Task 9: Wildcard (*) path traversal."""

    def test_wildcard_matches_all_array_elements(self):
        """messages.*.content should redact content in ALL messages."""
        obj = {"messages": [{"content": "a"}, {"content": "b"}]}
        paths = ["messages.*.content"]
        result = _redact_json(obj, paths)
        assert result["messages"][0]["content"] == "***"
        assert result["messages"][1]["content"] == "***"


class TestNestedPathTraversal:
    """Task 10: Nested wildcard path traversal."""

    def test_nested_wildcard_path(self):
        """choices.*.delta.content should redact nested content."""
        obj = {"choices": [{"delta": {"content": "text"}}]}
        paths = ["choices.*.delta.content"]
        result = _redact_json(obj, paths)
        assert result["choices"][0]["delta"]["content"] == "***"


class TestPathNotFound:
    """Task 11: JSON without matching paths."""

    def test_no_matching_paths_returns_unchanged(self):
        """JSON without any matching redaction paths should be returned unchanged."""
        obj = {"model": "gpt-4", "temperature": 0.7, "top_p": 0.9}
        paths = ["messages.*.content", "choices.*.message.content"]
        result = _redact_json(obj, paths)
        assert result == {"model": "gpt-4", "temperature": 0.7, "top_p": 0.9}


class TestSSEMalformed:
    """Task 12: Malformed SSE data lines."""

    def test_malformed_json_after_data_prefix_preserved(self):
        """Non-JSON after 'data:' prefix should be preserved as-is, no crash."""
        sse_body = "data: NOT VALID JSON\n\n"
        result = redact_content(sse_body.encode(), "openai_like")
        assert result.decode() == sse_body

    def test_malformed_sse_no_crash_mixed_with_valid(self):
        """Malformed SSE line preserved; valid JSON line still processed."""
        sse_body = 'data: {broken json}\n\ndata: {"valid": "json"}\n\n'
        result = redact_content(sse_body.encode(), "openai_like")
        decoded = result.decode()
        # First malformed line should be preserved as-is
        assert "data: {broken json}" in decoded
        # Second valid line should be processed (no crash)
        assert "data:" in decoded


class TestContentRedactionVsFullBody:
    """Task 13: Content redaction only applies content paths, not other sensitive fields."""

    def test_content_redaction_does_not_redact_api_key(self):
        """redact_content should NOT redact fields outside content paths (e.g. api_key)."""
        body = json.dumps(
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "secret message"}],
                "api_key": "sk-abc123",
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        # api_key is NOT in REDACT_CONTENT_PATHS, so it should be preserved
        assert result["api_key"] == "sk-abc123"

    def test_content_redaction_only_targets_content_paths(self):
        """redact_content should only redact fields defined in REDACT_CONTENT_PATHS."""
        body = json.dumps(
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "secret message"}],
                "metadata": {"user_id": "user123", "session": "abc"},
            }
        ).encode()
        result = json.loads(redact_content(body, "openai_like"))
        # metadata is not a content path, should be preserved entirely
        assert result["metadata"] == {"user_id": "user123", "session": "abc"}


class TestUnknownProviderType:
    """Task 14: Unknown provider_type returns body unchanged."""

    def test_unknown_provider_returns_body_unchanged(self):
        """redact_content with unknown provider_type should return body unchanged."""
        body = json.dumps({"messages": [{"content": "Hello"}]}).encode()
        result = redact_content(body, "unknown_provider")
        assert result == body

    def test_empty_provider_type_returns_body_unchanged(self):
        """redact_content with empty provider_type should return body unchanged."""
        body = json.dumps({"messages": [{"content": "Hello"}]}).encode()
        result = redact_content(body, "")
        assert result == body
