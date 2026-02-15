# Debug Mode Configuration

## Overview

The debug mode feature allows you to log detailed information about requests and responses for debugging purposes. It supports three levels of detail:

- `disabled` - No additional debug logging (default behavior)
- `headers_only` - Log request and response headers only
- `full_body` - Log request and response headers and body content (truncated to 10KB)

## Configuration

Debug mode is configured at the provider level.

### Provider Level

In each provider's `gateway_policy` section:

```yaml
providers:
  my_provider:
    gateway_policy:
      streaming_mode: "auto"
      debug_mode: "full_body"  # Provider-specific debug mode
```

## Behavior

When debug mode is enabled (`headers_only` or `full_body`), streaming is automatically disabled for that provider, even if streaming is enabled in the configuration. This is because debug mode requires buffering the entire request/response to log the complete content.

### Logging Format

Debug logs are written to standard output without prefixes for easy parsing:

```
Request to provider_name: POST /v1/chat/completions
Request headers: {'content-type': 'application/json', 'authorization': 'Bearer ...'}
Request body: {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}
Response from provider_name: 200
Response headers: {'content-type': 'application/json', 'content-length': '1234'}
Response body: {"choices": [{"message": {"content": "Hello! How can I help you?"}}]}
```

For `full_body` mode, body content is truncated to 10KB with "... (truncated)" suffix if it exceeds the limit.

## Usage Examples

### Enable debug mode for specific provider only

```yaml
providers:
  openai_provider:
    # Normal operation, no debug logging
    gateway_policy:
      debug_mode: "disabled"
  
  gemini_provider:
    # Debug mode enabled for this provider only
    gateway_policy:
      debug_mode: "headers_only"
```

## Important Notes

- Debug mode automatically disables streaming for the affected providers
- Body content is truncated to 10KB to prevent memory issues with large payloads
- Debug logs are written to standard output, so they will be captured by systemd/journald or docker-compose logs
- No sensitive data filtering is performed - ensure you understand the security implications of logging request/response bodies
