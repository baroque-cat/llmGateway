## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b pool-error-isolation`
- [x] 1.2 Run the full test suite to establish a passing baseline: `poetry run pytest tests/ -v --ignore=tests/stress/test_production_load.py`

## 2. Pool Error Isolation — `_send_proxy_request` (`base.py`)

- [x] 2.1 Add `elif isinstance(e, httpx.LocalProtocolError):` check after line 298 (`RemoteProtocolError`) in `src/providers/base.py`, setting `detail = " — connection pool saturated (all HTTP/2 streams in use)"`
- [x] 2.2 Replace the unconditional `CheckResult.fail(ErrorReason.NETWORK_ERROR, ...)` at lines 314-316 with conditional: `ErrorReason.BAD_REQUEST` for `LocalProtocolError`, `ErrorReason.NETWORK_ERROR` for everything else
- [x] 2.3 Verify pyright passes: `poetry run pyright src/providers/base.py`

## 3. Pool Health Summary — `get_health_summary()` (`pool.py`)

- [x] 3.1 Add `get_health_summary() -> dict` method to `CapacityAwareHttp2Pool` in `src/core/http2/pool.py` returning `total_connections`, `active_connections`, `idle_connections`, `h2_connections`, `h1_connections`, `active_h2_streams`, `max_h2_stream_capacity`, `queued_requests`
- [x] 3.2 Add `get_pool_health_summary() -> dict[str, dict]` method to `HttpClientFactory` in `src/core/http_client_factory.py` iterating over `_clients` and calling each transport pool's `get_health_summary()`
- [x] 3.3 Verify pyright passes: `poetry run pyright src/core/http2/pool.py src/core/http_client_factory.py`

## 4. Pool Health Logging — gateway background task

- [x] 4.1 Add `pool_health_log_interval_sec: int = Field(default=60, ge=0)` to `HttpClientConfig` in `src/config/schemas.py`
- [x] 4.2 Read `pool_health_log_interval_sec` from config in `HttpClientFactory.__init__`; store as `self._pool_health_log_interval_sec`
- [x] 4.3 Create `_pool_health_log_loop(factory: HttpClientFactory, interval_sec: int) -> None` async function in `src/services/gateway/gateway_service.py` (following `_cache_refresh_loop` pattern at lines 389-404)
- [x] 4.4 Launch `_pool_health_log_loop` as `asyncio.create_task(...)` in `create_app()` lifespan startup (after line 858), only when `interval_sec > 0`
- [x] 4.5 Cancel the task on shutdown in `create_app()` lifespan (after line 876)
- [x] 4.6 Add default `pool_health_log_interval_sec: 60` to `config/example_full_config.yaml` in the `http_client:` block
- [x] 4.7 Verify ruff + black: `poetry run ruff check src/` and `poetry run black src/ --check`

## 5. Quality Checks

- [x] 5.1 Run `poetry run pyright` — must pass with zero errors
- [x] 5.2 Run `poetry run ruff check src/ tests/` — must pass
- [x] 5.3 Run `poetry run black src/ tests/ --check` — must produce no changes

## 6. Testing

- [x] 6.1 Read `test-plan.md` Delegation Groups section
- [x] 6.2 Delegate group `pool-error-classification` to @Mr.Tester (scope: `tests/unit/providers/test_base.py`)
- [x] 6.3 Delegate group `pool-health-summary` to @Mr.Tester (scope: `tests/unit/core/http2/test_transport.py`)
- [x] 6.4 Delegate group `pool-health-factory` to @Mr.Tester (scope: `tests/unit/core/test_http_client_factory.py`)
- [x] 6.5 Delegate group `pool-gateway` to @Mr.Tester (scope: `tests/unit/services/test_gateway_core.py`)
- [x] 6.6 Delegate group `pool-health-config` to @Mr.Tester (scope: `tests/unit/config/test_http_client_config.py`)
- [x] 6.7 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 6.8 Re-delegate any groups affected by source fixes
- [x] 6.9 Verify all groups pass and coverage matches `test-plan.md`
- [x] 6.10 Run full test suite: `poetry run pytest tests/ -v --ignore=tests/stress/test_production_load.py`
