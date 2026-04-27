# Debug Mode Configuration

## Overview

The debug mode feature allows you to log detailed request/response information
for troubleshooting. Three levels are available:

- ``disabled`` — No additional debug logging (default behavior).
- ``no_content`` — Log all request/response metadata and parameters,
  but **redact** content and thinking/reasoning fields per provider.
- ``full_body`` — Log full request and response including all bodies,
  with sensitive fields (``api_key``, ``token``) redacted.

## Configuration

Debug mode is configured per provider in its ``gateway_policy`` section:

```yaml
providers:
  my_provider:
    gateway_policy:
      streaming_mode: "auto"
      debug_mode: "no_content"  # Provider-specific debug mode
```

Valid values: ``"disabled"``, ``"no_content"``, ``"full_body"``.

The obsolete value ``"headers_only"`` is **no longer accepted** — it will cause
a Pydantic validation error at startup with a clear message listing the valid
values.

## Mode Comparison Table

| Mode        | Headers | Params | Content | Thinking | Sensitive fields |
|-------------|---------|--------|---------|----------|------------------|
| disabled    | ❌      | ❌     | ❌      | ❌        | —                |
| no_content  | ✅      | ✅     | ███    | ███      | ███              |
| full_body   | ✅      | ✅     | ✅      | ✅       | ███              |

- **Sensitive fields** (``api_key``, ``token``, ``secret``, ``password``,
  ``Authorization``) are **always** redacted in both ``no_content`` and
  ``full_body`` modes.

## Content Redaction (no_content mode)

When ``debug_mode: "no_content"``, the gateway redacts content and
thinking/reasoning fields. The redaction paths are **provider-specific**:

### OpenAI-like (OpenAI, DeepSeek, Moonshot, etc.)

| Direction | Redacted paths |
|-----------|---------------|
| Request   | ``messages.*.content``, ``messages.*.content.*.text``, ``messages.*.content.*.image_url`` |
| Response  | ``choices.*.message.content``, ``choices.*.delta.content``, ``choices.*.delta.reasoning_content`` |

### Gemini

| Direction | Redacted paths |
|-----------|---------------|
| Request   | ``contents.*.parts.*.text``, ``systemInstruction.parts.*.text`` |
| Response  | ``candidates.*.content.parts.*.text`` |

### Anthropic

| Direction | Redacted paths |
|-----------|---------------|
| Request   | ``messages.*.content``, ``messages.*.content.*.text``, ``system`` |
| Response  | ``content.*.text``, ``content.*.thinking``, ``content.*.data`` |
| SSE       | ``content_block.text``, ``content_block.thinking``, ``delta.text``, ``delta.thinking`` |

All replaced values become the literal string ``"***"``.

## Interaction with Streaming

When ``no_content`` or ``full_body`` is enabled, streaming is **automatically
disabled** for that provider. The entire response is buffered before logging
and returned to the client as a single ``Response`` (not ``StreamingResponse``).

This is necessary because debug mode requires the complete request/response
trace for logging. Streaming would bypass the buffering step.

## Interaction with Retry Policies

When debug mode is enabled (``no_content`` or ``full_body``), **retry policies
are automatically disabled**. This is because debug mode requires a single,
deterministic request/response trace — retries would obscure which attempt
succeeded.

A **WARNING** is logged at startup if both debug mode and retry are configured
for the same provider:

```
WARNING: [Gateway Startup] Instance 'my_provider': Retry policy is CONFIGURED but
WILL BE IGNORED because debug mode 'full_body' takes priority. Disable debug mode
to restore retry behavior.
```

If you need both debug logging **and** retry resilience, use debug mode only
for troubleshooting and disable it for normal operation.

## Log Format

Debug logs are written to standard output using Python's `logging` module:

```
Request to provider_name: POST /v1/chat/completions
Request headers: {'content-type': 'application/json', 'authorization': 'Bearer ***'}
Request body: {"model": "gpt-4", "messages": [{"role": "user", "content": "***"}]}
Response from provider_name: 200
Response headers: {'content-type': 'application/json'}
Response body: {"choices": [{"message": {"content": "***"}}]}
```

### Log format in containerized environments

When running in Docker (via `docker-compose`), the container runtime's log
driver (typically `json-file`) captures stdout line-by-line and prepends an
**ISO 8601 timestamp**. Each line has its own timestamp, even continuation
lines of multi-line log messages. This is normal container behavior and does
not indicate streaming.

**Multiline bodies are collapsed** — literal newlines are replaced with the
escape sequence ``\n`` before logging. This produces clean single-line output:

```
Response body: data: {"choices":[{"delta":{"content":"***"}}]}\ndata: [DONE]\n\n
```

## Sensitive Field Redaction

The following fields are **always** redacted in both ``full_body`` and
``no_content`` modes:

| Field           | Logged as            |
|-----------------|----------------------|
| ``api_key``     | ``"***"``            |
| ``token``       | ``"***"``            |
| ``secret``      | ``"***"``            |
| ``password``    | ``"***"``            |
| ``Authorization`` header (``Bearer`` token) | ``Bearer ***`` |
| Other auth headers (``x-goog-api-key``, ``x-api-key``) | ``***`` |

## Usage Examples

### Enable no_content for a single provider

```yaml
providers:
  gemini_production:
    gateway_policy:
      debug_mode: "no_content"
      streaming_mode: "auto"  # Will be disabled automatically
```

### Enable full_body for deep debugging

```yaml
providers:
  deepseek_main:
    gateway_policy:
      debug_mode: "full_body"
```

### Mixed configuration

```yaml
providers:
  openai_prod:
    # Normal operation
    gateway_policy:
      debug_mode: "disabled"

  gemini_debug:
    # Debug without exposing content
    gateway_policy:
      debug_mode: "no_content"

  anthropic_full:
    # Show everything except sensitive fields
    gateway_policy:
      debug_mode: "full_body"
```

## Important Notes

- Debug mode automatically disables streaming for the affected providers
- Debug mode automatically disables retry policies — a WARNING is logged at startup
- Content fields are redacted per provider type in ``no_content`` mode
- Sensitive fields (``api_key``, ``token``, ``secret``, ``password``) are always redacted
- Debug logs are written to standard output, captured by systemd/journald or docker-compose
- Multiline SSE bodies are collapsed to single lines for clean log output
- The ``"headers_only"`` value is no longer valid — use ``"no_content"`` instead
- **Debug mode does NOT affect adaptive batching**: the background worker's
  adaptive batch controller operates independently of per-request debug logging.
  Retries disabled by debug mode apply to the gateway, not to the worker's
  probe verification loop.
