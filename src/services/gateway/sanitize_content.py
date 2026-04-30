#!/usr/bin/env python3

"""
Provider-aware content redaction for debug logging in `no_content` mode.

This module defines JSON paths for content and thinking/reasoning fields
across all supported providers and provides functions to recursively
redact those fields from request/response bodies, including SSE payloads.

Architecture:
    ``REDACT_CONTENT_PATHS`` — static dictionary mapping provider_type to
    request/response JSON paths (using ``*`` wildcards for array indices).

    ``redact_content()`` — public API: takes raw bytes and a provider_type,
    returns sanitized bytes with content fields replaced by ``"***"``.

    ``_redact_json()`` — recursive JSON tree traversal with wildcard matching.

    ``_redact_sse()`` — SSE-aware redaction: splits on ``\\n\\n``, parses each
    ``data:`` line as JSON, applies redaction, and reassembles.
"""

import json

# ---------------------------------------------------------------------------
# Content redaction paths per provider type
# ---------------------------------------------------------------------------
# Paths use dot-separated segments with ``*`` wildcards for array indices.
# The ``*`` wildcard matches ALL elements of an array at that position.
# SSE-specific paths are stored under the "response" key since SSE is used
# for response streaming.
# ---------------------------------------------------------------------------

REDACT_CONTENT_PATHS: dict[str, dict[str, list[str]]] = {
    "openai_like": {
        "request": [
            "messages.*.content",
            "messages.*.content.*.text",
            "messages.*.content.*.image_url",
        ],
        "response": [
            "choices.*.message.content",
            "choices.*.delta.content",
            "choices.*.delta.reasoning_content",
        ],
    },
    "gemini": {
        "request": [
            "contents.*.parts.*.text",
            "systemInstruction.parts.*.text",
        ],
        "response": [
            "candidates.*.content.parts.*.text",
        ],
    },
    "anthropic": {
        "request": [
            "messages.*.content",
            "messages.*.content.*.text",
            "system",
        ],
        "response": [
            # Non-streaming response paths
            "content.*.text",
            "content.*.thinking",
            "content.*.data",
            # SSE event paths (used in Anthropic streaming)
            "content_block.text",
            "content_block.thinking",
            "delta.text",
            "delta.thinking",
        ],
    },
}


# ---------------------------------------------------------------------------
# Recursive JSON redaction with wildcard path traversal
# ---------------------------------------------------------------------------


def _redact_json(obj: object, paths: list[str]) -> object:
    """
    Recursively traverse a parsed JSON object and replace values at matched paths
    with the string ``"***"``.

    Paths use dot-separated segments.  A ``*`` segment acts as a wildcard that
    matches every element of an array at that level.

    Args:
        obj: A parsed JSON value (dict, list, or scalar).
        paths: List of dot-separated path strings (e.g. ``["messages.*.content"]``).

    Returns:
        The (possibly mutated) object with matched leaf values replaced.
    """
    if not paths:
        return obj

    for path in paths:
        _apply_path(obj, path.split("."), 0)
    return obj


def _apply_path(current: object, segments: list[str], depth: int) -> None:
    """Mutate ``current`` in-place for a single path, starting at ``segments[depth:]``."""
    if depth >= len(segments):
        return  # No more segments — shouldn't happen for valid paths

    segment = segments[depth]
    is_last = depth == len(segments) - 1

    # fmt: off
    if segment == "*":
        if isinstance(current, list):
            for i in range(len(current)):  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
                if is_last:
                    current[i] = _redact_leaf(current[i])  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
                else:
                    _apply_path(current[i], segments, depth + 1)  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
        return

    if isinstance(current, dict) and segment in current:
        if is_last:
            current[segment] = _redact_leaf(current[segment])  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
        else:
            _apply_path(current[segment], segments, depth + 1)  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
    # fmt: on


def _redact_leaf(value: object) -> object:
    """Replace the leaf value with ``"***"``.

    * Scalar values (str, int, float, bool, None) → ``"***"``.
    * List values → each scalar element replaced with ``"***"``.
    * Dict values → each scalar value replaced with ``"***"``.

    Returns:
        The (possibly mutated) value.  Callers must assign the result back
        into the parent container (dict key or list index).
    """
    # fmt: off
    if isinstance(value, list):
        for i in range(len(value)):  # pyright: ignore[reportUnknownArgumentType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
            if isinstance(value[i], (str, int, float, bool, type(None))):
                value[i] = "***"
        return value  # pyright: ignore[reportUnknownVariableType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
    elif isinstance(value, dict):
        for key in value:  # pyright: ignore[reportUnknownVariableType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
            if isinstance(value[key], (str, int, float, bool, type(None))):
                value[key] = "***"
        return value  # pyright: ignore[reportUnknownVariableType]  # TODO: remove after introducing JSONValue recursive type in core/models.py
    else:
        return "***"
    # fmt: on


# ---------------------------------------------------------------------------
# SSE-aware redaction
# ---------------------------------------------------------------------------


def _redact_sse(body_str: str, paths: list[str]) -> str:
    """
    Apply content redaction to an SSE (Server-Sent Events) payload string.

    Splits on ``\\n\\n`` (event boundary), then for each event line:
    if it starts with ``data: ``, the JSON after the prefix is parsed,
    redacted via ``_redact_json``, and reassembled.

    Non-``data:`` lines and non-JSON content are preserved verbatim.

    Args:
        body_str: Raw SSE body string (decoded UTF-8).
        paths: List of dot-separated content redaction paths.

    Returns:
        SSE string with content fields redacted inside each ``data:`` payload.
    """
    if not paths:
        return body_str

    events = body_str.split("\n\n")
    sanitized_events: list[str] = []

    for event in events:
        lines = event.split("\n")
        sanitized_lines: list[str] = []

        for line in lines:
            if line.startswith("data: "):
                json_str = line.removeprefix("data: ")
                try:
                    data_obj = json.loads(json_str)
                    redacted_obj = _redact_json(data_obj, paths)
                    line = f"data: {json.dumps(redacted_obj)}"
                except (json.JSONDecodeError, TypeError):
                    # Malformed JSON inside data: — leave line as-is
                    pass
            sanitized_lines.append(line)

        sanitized_events.append("\n".join(sanitized_lines))

    return "\n\n".join(sanitized_events)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_content(body: bytes, provider_type: str) -> bytes:
    """
    Apply provider-specific content redaction to a request/response body.

    This is the **public entry point** for ``no_content`` mode sanitization.
    It detects SSE vs plain JSON payloads and delegates accordingly.

    Args:
        body: Raw request or response body bytes.
        provider_type: The provider type string (e.g. ``"openai_like"``, ``"gemini"``,
            ``"anthropic"``).  Must be a key in ``REDACT_CONTENT_PATHS``.

    Returns:
        Sanitized body bytes with content fields replaced by ``"***"``.
        If the provider type is unknown or has no paths, the body is returned
        unchanged.
    """
    provider_paths = REDACT_CONTENT_PATHS.get(provider_type)
    if not provider_paths:
        return body

    # Collect all paths for both request and response directions.
    # SSE-specific paths are stored under "response".
    all_paths: list[str] = []
    for direction in ("request", "response"):
        all_paths.extend(provider_paths.get(direction, []))

    if not all_paths:
        return body

    try:
        decoded = body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return body

    # Detect SSE payloads (used by Anthropic and other streaming providers)
    if "data: " in decoded:
        result = _redact_sse(decoded, all_paths)
        return result.encode("utf-8")

    # Plain JSON detection
    stripped = decoded.strip()
    if stripped.startswith(("{", "[")):
        try:
            obj = json.loads(stripped)
            redacted = _redact_json(obj, all_paths)
            return json.dumps(redacted).encode("utf-8")
        except (json.JSONDecodeError, TypeError):
            return body

    return body
