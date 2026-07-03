## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b feat/h2-throughput-bottleneck-tests` 
- [x] 1.2 Run the full test suite to establish a passing baseline before making changes

## 2. Config Schema Changes

- [x] 2.1 Add `max_concurrent_streams_per_connection: int = Field(default=5, ge=1, le=1000)` to `ProviderConfig` in `src/config/schemas.py`
- [x] 2.2 Remove `dedicated_http_client: bool = True` field from `ProviderConfig` in `src/config/schemas.py`
- [x] 2.3 Remove `"dedicated_http_client": True` from the provider template in `src/config/defaults.py`
- [x] 2.4 Remove `dedicated_http_client: true` lines from all 4 providers in `config/example_full_config.yaml`
- [x] 2.5 Add `max_concurrent_streams_per_connection` with per-provider values and comments to `config/example_full_config.yaml` (e.g., qwen=5, openai=100, anthropic=50, deepseek=10)

## 3. Remove dedicated_http_client Code Path

- [x] 3.1 Simplify `_get_cache_key_for_provider` in `src/core/http_client_factory.py` to always `return provider_name` (remove the `dedicated_http_client` branch)
- [x] 3.2 Delete `_get_cache_key_for_proxy` method entirely from `src/core/http_client_factory.py`
- [x] 3.3 Verify `get_proxy_config()` is still called in `get_client_for_provider` for the `proxy=` kwarg (client creation, not key derivation)

## 4. Pass Cap Through the Transport Chain

- [x] 4.1 In `HttpClientFactory.get_client_for_provider` (`src/core/http_client_factory.py`): read `provider_config.max_concurrent_streams_per_connection` and pass as `max_concurrent_streams_cap` to `CapacityAwareHttp2Transport`
- [x] 4.2 Add `max_concurrent_streams_cap: int | None = None` and `provider_name: str = "unknown"` parameters to `CapacityAwareHttp2Transport.__init__` (`src/core/http2/transport.py`); pass to `CapacityAwareHttp2Pool`
- [x] 4.3 Add `max_concurrent_streams_cap: int | None = None` and `provider_name: str = "unknown"` parameters to `CapacityAwareHttp2Pool.__init__` (`src/core/http2/pool.py`); store as instance attributes
- [x] 4.4 In `CapacityAwareHttp2Pool.create_connection` (`src/core/http2/pool.py`): pass `max_concurrent_streams_cap` and `connection_label` to `CapacityAwareHTTPConnection`
- [x] 4.5 Add `max_concurrent_streams_cap: int | None = None` and `connection_label: str = ""` parameters to `CapacityAwareHTTPConnection.__init__` (`src/core/http2/connection.py`); store as instance attributes
- [x] 4.6 In `CapacityAwareHTTPConnection.handle_async_request` (`src/core/http2/connection.py`): pass `max_concurrent_streams_cap` to `FixedHTTP2Connection` constructor
- [x] 4.7 Add `max_concurrent_streams_cap: int | None = None` parameter to `FixedHTTP2Connection.__init__` (`src/core/http2/h2_connection.py`); store as `self._max_streams_cap`

## 5. Apply Cap in FixedHTTP2Connection

- [x] 5.1 In `_receive_remote_settings_change` (`src/core/http2/h2_connection.py`): apply cap in the `min()` call — `new_max_streams = min(server_advertised, local_settings, self._max_streams_cap)` when cap is not None
- [x] 5.2 In `handle_async_request` (`src/core/http2/h2_connection.py`): apply cap to `local_settings_max_streams` before semaphore initialization — `local_settings_max_streams = min(local_settings, cap)` when cap is not None

## 6. Connection Labels

- [x] 6.1 Add `_connection_ordinal: int = 0` counter to `CapacityAwareHttp2Pool.__init__` (`src/core/http2/pool.py`)
- [x] 6.2 In `CapacityAwareHttp2Pool.create_connection` (`src/core/http2/pool.py`): generate label `f"{self._provider_name}-conn-{self._connection_ordinal}"`, increment counter, pass to `CapacityAwareHTTPConnection`
- [x] 6.3 Add `connection_label` to `CapacityAwareHTTPConnection.__init__` and store as `self._connection_label` (`src/core/http2/connection.py`)
- [x] 6.4 Log connection creation at INFO level in `create_connection` with label and origin

## 7. Per-Connection Health Breakdown

- [x] 7.1 In `CapacityAwareHttp2Pool.get_health_summary` (`src/core/http2/pool.py`): add `connections` key with list of per-connection dicts, each containing `label`, `state`, `protocol`, `active_streams`, `max_streams`
- [x] 7.2 Update `HttpClientFactory.get_pool_health_summary` (`src/core/http_client_factory.py`) if needed to propagate the new `connections` key
- [x] 7.3 Update `_pool_health_log_loop` in `src/services/gateway/gateway_service.py` to emit per-connection log lines: `HTTP_POOL_CONN | <cache_key> | <label> | <state> | <protocol> | streams: <active>/<max>`

## 8. Connection Closure Logging

- [x] 8.1 Log connection closure at INFO level when a connection is evicted or closed in `_assign_requests_to_connections` (`src/core/http2/pool.py`)
- [x] 8.2 Log connection closure when `aclose()` is called on a connection (hook into existing close paths)

## 9. Testing

- [x] 9.1 Read `test-plan.md` Delegation Groups section
- [x] 9.2 Delegate group `config-unit` to @Mr.Tester (scope: tests/unit/config/test_schemas.py, test_validator.py, test_defaults.py, tests/integration/test_config_examples.py)
- [x] 9.3 Delegate group `factory-unit` to @Mr.Tester (scope: tests/unit/core/test_http_client_factory.py)
- [x] 9.4 Delegate group `h2-connection-unit` to @Mr.Tester (scope: tests/unit/core/http2/test_h2_connection.py)
- [x] 9.5 Delegate group `pool-unit` to @Mr.Tester (scope: tests/unit/core/http2/test_pool.py, test_connection.py)
- [x] 9.6 Delegate group `gateway-unit` to @Mr.Tester (scope: tests/unit/services/test_gateway_core.py)
- [x] 9.7 Delegate group `cap-stress` to @Mr.Tester (scope: tests/stress/test_cap_prevents_freeze.py)
- [x] 9.8 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 9.9 Re-delegate any groups affected by source fixes
- [x] 9.10 Verify all groups pass and coverage matches `test-plan.md`

## 10. Quality Gates

- [x] 10.1 Run `poetry run pyright` — fix all type errors
- [x] 10.2 Run `poetry run ruff check src/ tests/` — fix all lint issues
- [x] 10.3 Run `poetry run black src/ tests/` — fix all formatting issues
- [x] 10.4 Run `poetry run pytest --cov=src` — verify all tests pass
- [x] 10.5 Verify CI pipeline passes (pyright + ruff + black + pytest + coverage)
