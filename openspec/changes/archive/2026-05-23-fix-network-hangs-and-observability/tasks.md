## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b fix/network-hangs-and-observability`
- [x] 1.2 Run the full test suite to establish a passing baseline before making changes: `poetry run pytest`

## 2. Config Schema — Models and Defaults

- [x] 2.1 Add `total: float = Field(default=600.0, gt=0)` to `TimeoutConfig` in `src/config/schemas.py`
- [x] 2.2 Update existing `TimeoutConfig` field defaults: `connect=10.0`, `read=120.0`, `write=20.0`, `pool=15.0`
- [x] 2.3 Add new `HttpClientPoolConfig` model with `max_connections`, `max_keepalive_connections`, `keepalive_expiry` in `src/config/schemas.py`
- [x] 2.4 Add new `HttpClientConfig` model wrapping `pool: HttpClientPoolConfig` and `http2: bool` in `src/config/schemas.py`
- [x] 2.5 Add new `HttpClientLoggingConfig` model with `httpx_level`, `httpcore_level`, `trace_enabled` in `src/config/schemas.py`
- [x] 2.6 Add `http_client: HttpClientConfig = Field(default_factory=HttpClientConfig)` to root `Config` model
- [x] 2.7 Add `http_client: HttpClientLoggingConfig = Field(default_factory=HttpClientLoggingConfig)` to `LoggingConfig` model
- [x] 2.8 Add `command_timeout: float = Field(default=30.0, gt=0)` and `connect_timeout: float = Field(default=60.0, gt=0)` to `DatabasePoolConfig`
- [x] 2.9 Change `ProviderConfig.dedicated_http_client` default from `False` to `True`
- [x] 2.10 Update `src/config/defaults.py`: add http_client section defaults, database pool timeout defaults, update timeout defaults, change dedicated_http_client to True
- [x] 2.11 Add `get_http_client_config()` method to `ConfigAccessor` in `src/core/accessor.py`
- [x] 2.12 Run `poetry run pyright` to verify schema changes are type-correct

## 3. Logging Configuration

- [x] 3.1 Add `_setup_http_client_logging(cfg)` function in `src/config/logging_config.py` that sets httpx and httpcore logger levels from `HttpClientLoggingConfig`
- [x] 3.2 Call `_setup_http_client_logging()` from `setup_logging()` in `src/config/logging_config.py`
- [x] 3.3 Add `trace_enabled` support: if `trace_enabled=True`, store a trace handler callable in the config for `HttpClientFactory` to use

## 4. HTTP Client Factory — Connection Pool Limits

- [x] 4.1 In `HttpClientFactory.__init__`, read `HttpClientConfig` from accessor and store pool config
- [x] 4.2 In `get_client_for_provider()`, construct `httpx.Limits(max_connections=..., max_keepalive_connections=..., keepalive_expiry=...)` from stored config
- [x] 4.3 Pass `limits` and `http2` config value to `httpx.AsyncClient()` constructor
- [x] 4.4 If `trace_enabled` is True, add `extensions={"trace": trace_handler}` to request dispatch

## 5. Provider Base — Enhanced Network Error Logging

- [x] 5.1 In `AIBaseProvider._send_proxy_request()` except `httpx.RequestError` block (`src/providers/base.py:286-293`): extract `type(e).__name__`, `str(request.url)`, and add `isinstance()` chain for detail strings (`ReadTimeout` → "no data received", `RemoteProtocolError` → "HTTP/2 protocol error", `PoolTimeout` → "connection pool exhausted", `ConnectError` → "TCP connection failed", etc.)
- [x] 5.2 Format new structured error message: `"Upstream network error: [{error_type}] provider='{self.name}' url='{url}'{detail} — {e}"`
- [x] 5.3 Ensure the `CheckResult.fail()` call still receives the enhanced error message

## 6. Gateway Service — Request Lifecycle Timeout

- [x] 6.1 Wrap the `while True` retry loop in `_handle_buffered_retryable_request()` (`gateway_service.py:546`) with `async with asyncio.timeout(timeout_sec)`, reading `timeout_sec` from `provider_config.timeouts.total`
- [x] 6.2 Add `except asyncio.TimeoutError` handler after the `while True` loop: log structured error with total attempts, key errors, server errors, last error reason
- [x] 6.3 Return `JSONResponse(status_code=504, content={"error": "Gateway timeout: upstream request did not complete within ...", "attempts": ..., "last_error": ...})` on timeout
- [x] 6.4 Enhance retry attempt failure log at `gateway_service.py:592-594` to include key ID and upstream status code: `f"... Reason: [{reason}], Key: #{key_id}, Status: {status_code}"`

## 7. Database — Query Timeouts

- [x] 7.1 Update `init_db_pool()` signature in `src/db/database.py` to accept `command_timeout: float` and `connect_timeout: float` parameters
- [x] 7.2 Pass `command_timeout` and `connect_timeout` to `asyncpg.create_pool()` call
- [x] 7.3 Update call sites: `gateway_service.py:788` and `keeper.py:322` to pass timeouts from `accessor.get_pool_config()`
- [x] 7.4 In `src/services/db_maintainer.py`, before `VACUUM ANALYZE` execution, add `await conn.execute("SET statement_timeout = 0")` to override pool-level timeout

## 8. Example Configs

- [x] 8.1 Update `config/example_full_config.yaml`:
  - Add `http_client` top-level section with `http2: true` and `pool: { max_connections: 200, max_keepalive_connections: 50, keepalive_expiry: 30.0 }`
  - Add `http_client` section under `logging` with `httpx_level: "WARNING"`, `httpcore_level: "WARNING"`, `trace_enabled: false`
  - Add `command_timeout: 30.0` and `connect_timeout: 60.0` to `database.pool`
  - Update per-provider `timeouts`: `connect: 10.0`, `read: 120.0`, `write: 20.0`, `pool: 15.0`, `total: 600.0`
  - Change `dedicated_http_client: false` → `dedicated_http_client: true` for all providers
- [x] 8.2 Update `config/example_minimal_config.yaml`:
  - Add new `http_client` section with defaults
  - Add `database.pool.command_timeout` and `connect_timeout`

## 9. Testing

- [x] 9.1 Read `test-plan.md` Delegation Groups section
- [x] 9.2 Delegate group `config-timeout` to @Mr.Tester (scope: `tests/unit/config/test_timeout_config.py` — CREATE, verify `total` field, updated defaults)
- [x] 9.3 Delegate group `config-http-client` to @Mr.Tester (scope: `tests/unit/config/test_http_client_config.py` — CREATE, verify `HttpClientPoolConfig`, `HttpClientConfig`, `HttpClientLoggingConfig`)
- [x] 9.4 Delegate group `config-logging` to @Mr.Tester (scope: existing logging config tests — MODIFY, verify httpx/httpcore level settings)
- [x] 9.5 Delegate group `config-database` to @Mr.Tester (scope: existing database pool config tests — MODIFY, verify `command_timeout`/`connect_timeout`)
- [x] 9.6 Delegate group `config-defaults` to @Mr.Tester (scope: existing defaults tests — MODIFY, verify `dedicated_http_client=True`, updated timeout values)
- [x] 9.7 Delegate group `gateway-timeout` to @Mr.Tester (scope: `tests/unit/services/test_gateway_timeout.py` — CREATE, verify `asyncio.timeout` enforcement, 504 response structure)
- [x] 9.8 Delegate group `http-client-factory` to @Mr.Tester (scope: existing `tests/unit/core/test_http_client_factory.py` — MODIFY, verify `httpx.Limits` construction, pool config application)
- [x] 9.9 Delegate group `provider-error-logging` to @Mr.Tester (scope: `tests/unit/providers/test_base.py` — MODIFY, verify new error log format includes type, URL, detail)
- [x] 9.10 Delegate group `gateway-routing` to @Mr.Tester (scope: existing gateway routing tests — MODIFY, verify enhanced retry attempt logging)
- [x] 9.11 Delegate group `database-timeout` to @Mr.Tester (scope: existing DB init + maintainer tests — MODIFY, verify `command_timeout` pool param, VACUUM timeout override)
- [x] 9.12 Review all @Mr.Tester reports and fix any source-level bugs discovered
- [x] 9.13 Re-delegate any groups affected by source fixes
- [x] 9.14 Verify all groups pass and coverage matches `test-plan.md`
- [x] 9.15 Run full CI pipeline: `poetry run pyright && poetry run ruff check src/ tests/ && poetry run black --check src/ tests/ && poetry run pytest --cov=src`
