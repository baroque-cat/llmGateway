## ADDED Requirements

### Requirement: Independent httpx and httpcore log level control
The `LoggingConfig` schema SHALL include a nested `http_client` section (`HttpClientLoggingConfig`) with fields `httpx_level` (default `"WARNING"`), `httpcore_level` (default `"WARNING"`), and `trace_enabled` (default `False`). The `setup_logging()` function SHALL apply these levels to the `"httpx"` and `"httpcore"` Python loggers independently from the application `level`.

#### Scenario: Default config silences httpx and httpcore
- **WHEN** the YAML config contains `logging: { level: "INFO" }` without an `http_client` section
- **THEN** the httpx logger level SHALL be `WARNING`
- **AND** the httpcore logger level SHALL be `WARNING`
- **AND** no httpx or httpcore messages SHALL appear at log level `INFO`

#### Scenario: httpcore_level debug enables HTTP/2 tracing
- **WHEN** the YAML config contains `logging: { http_client: { httpcore_level: "DEBUG" } }`
- **THEN** httpcore SHALL emit log messages at `DEBUG` level including `http2.send_request_headers`, `http2.receive_response_headers`, and `http2.response_closed` events

#### Scenario: httpcore_level warning prevents noise at INFO
- **WHEN** the YAML config contains `logging: { level: "INFO", http_client: { httpcore_level: "WARNING" } }`
- **THEN** even though the root logger is at `INFO`, httpcore SHALL NOT emit INFO-level messages

### Requirement: Enhanced network error logging format
The `except httpx.RequestError` handler in `AIBaseProvider._send_proxy_request()` SHALL log a structured error message including the exception type name, provider name, upstream URL, and human-readable detail specific to the exception subtype.

#### Scenario: ReadTimeout logged with detail
- **WHEN** `_send_proxy_request()` catches `httpx.ReadTimeout` for provider `deepseek-home` at URL `https://api.deepseek.com/v1/chat/completions`
- **THEN** the log message SHALL contain `"[ReadTimeout]"`, `"provider='deepseek-home'"`, `"url='https://api.deepseek.com/v1/chat/completions'"`, and `"no data received (read_timeout=300s)"`

#### Scenario: RemoteProtocolError logged with detail
- **WHEN** `_send_proxy_request()` catches `httpx.RemoteProtocolError` for provider `deepseek-home`
- **THEN** the log message SHALL contain `"[RemoteProtocolError]"` and `"HTTP/2 protocol error (server may have reset connection)"`

#### Scenario: PoolTimeout logged with detail
- **WHEN** `_send_proxy_request()` catches `httpx.PoolTimeout` for provider `deepseek-home`
- **THEN** the log message SHALL contain `"[PoolTimeout]"` and `"connection pool exhausted"`

#### Scenario: Unknown RequestError subtype logged without extra detail
- **WHEN** `_send_proxy_request()` catches an `httpx.RequestError` subclass not explicitly handled (e.g., `httpx.CloseError`)
- **THEN** the log message SHALL still contain the exception type name, provider name, and URL, but no extra human-readable detail

### Requirement: Enhanced retry attempt logging
The retry attempt failure log in `_handle_buffered_retryable_request()` SHALL include the key ID and HTTP status code from the failed attempt.

#### Scenario: Retry failure log includes key and status
- **WHEN** an attempt fails with reason `network_error` using key ID 42 with upstream status 503
- **THEN** the log message SHALL include `"Attempt N failed for 'deepseek-home'. Reason: [network_error], Key: #42, Status: 503"`
