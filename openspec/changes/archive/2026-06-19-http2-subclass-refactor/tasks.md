## 1. Environment

- [x] 1.1 Run the full test suite to establish a passing baseline: `poetry run pytest tests/ -v`
- [x] 1.2 Run pyright baseline: `poetry run pyright`

## 2. Dependency Freezing

- [x] 2.1 Add `httpcore = "1.0.9"` to `[project.dependencies]` in `pyproject.toml`
- [x] 2.2 Add `h2 = ">=4.3.0,<5.0"` to `[project.dependencies]` in `pyproject.toml`
- [x] 2.3 Run `poetry lock --no-update` to verify constraints resolve cleanly
- [x] 2.4 Verify `uv.lock` also resolves `httpcore==1.0.9` (check the file)
- [x] 2.5 Add CI version check to `.github/workflows/quality.yml`: `python -c "import httpcore; assert httpcore.__version__ == '1.0.9'"`

## 3. Package Scaffold

- [x] 3.1 Create directory `src/core/http2/`
- [x] 3.2 Create `src/core/http2/__init__.py` with public API exports and docstring

## 4. NonBlockingSemaphore (`semaphore.py`)

- [x] 4.1 Create `src/core/http2/semaphore.py` with `NonBlockingSemaphore(AsyncSemaphore)`
- [x] 4.2 Implement `acquire_nowait()` with asyncio (anyio.WouldBlock) and trio (trio.WouldBlock) backends
- [x] 4.3 Ensure `setup()` lazy-initialization is preserved from parent class

## 5. FixedHTTP2Connection (`h2_connection.py`)

- [x] 5.1 Create `src/core/http2/h2_connection.py` with `FixedHTTP2Connection(AsyncHTTP2Connection)`
- [x] 5.2 Add `__init__` with `on_capacity_update` parameter and `_closed_streams: set[int]`
- [x] 5.3 Override `_response_closed()`: check `_closed_streams`, call `reset_stream` for non-closed streams, conditional semaphore release (`len(self._events) <= self._max_streams`), close connection on reset
- [x] 5.4 Override `_receive_events()`: add `_closed_streams.add(event.stream_id)` for StreamEnded/StreamReset events
- [x] 5.5 Override `_receive_remote_settings_change()`: call `self._on_capacity_update()` after semaphore adjustment
- [x] 5.6 Override `is_available()`: add `len(self._events) < self.max_concurrent_requests()` check
- [x] 5.7 Add `max_concurrent_requests()`: return `self._max_streams` if `_sent_connection_init` else `1`
- [x] 5.8 Override `handle_async_request()`: copy from httpcore 1.0.9, replace `acquire()` with `acquire_nowait()`, add state rollback on failure. Document the reason for full method copy in docstring.
- [x] 5.9 Replace `AsyncSemaphore(local_settings_max_streams)` with `NonBlockingSemaphore(local_settings_max_streams)` in the copied method

## 6. CapacityAwareHTTPConnection (`connection.py`)

- [x] 6.1 Create `src/core/http2/connection.py` with `CapacityAwareHTTPConnection(AsyncHTTPConnection)`
- [x] 6.2 Add `__init__` with `on_capacity_update` parameter
- [x] 6.3 Override `handle_async_request()`: create `FixedHTTP2Connection` instead of `AsyncHTTP2Connection` when HTTP/2 negotiated
- [x] 6.4 Add `max_concurrent_requests()`: delegate to `self._connection.max_concurrent_requests()` or return `1`

## 7. CapacityAwareHttp2Transport (`transport.py`)

- [x] 7.1 Create `src/core/http2/transport.py` with `CapacityAwareHttp2Transport(AsyncConnectionPool)`
- [x] 7.2 Override `create_connection()`: pass `on_capacity_update=self._connection_capacity_updated` to `CapacityAwareHTTPConnection`
- [x] 7.3 Override `_assign_requests_to_connections()`: add `connection_request_count` tracking, check `connection_request_count[conn] < self._max_concurrent_requests(conn)`, increment on assignment
- [x] 7.4 Add `_connection_capacity_updated()`: run `_assign_requests_to_connections()` under `_optional_thread_lock`, close returned connections
- [x] 7.5 Add `_max_concurrent_requests(connection)`: return `connection.max_concurrent_requests()` or `1` on AttributeError

## 8. Integration

- [x] 8.1 Import `CapacityAwareHttp2Transport` in `src/core/http_client_factory.py`
- [x] 8.2 In `get_client_for_provider()`, create `CapacityAwareHttp2Transport` with pool config values
- [x] 8.3 Pass `transport=transport` to `httpx.AsyncClient()`
- [x] 8.4 Remove `apply_patch()` import and call from `main.py` (line ~23)
- [x] 8.5 Remove `apply_patch()` import and call from `tests/stress/conftest.py` (line ~19)

## 9. Cleanup

- [x] 9.1 Delete `src/core/httpcore_patch.py`
- [x] 9.2 Delete `tests/stress/test_stream_desync_patch.py` (replaced by `tests/unit/core/http2/test_h2_connection.py`)
- [x] 9.3 Update `docs/HTTP2_STRESS_TESTS.md`: replace monkey-patch architecture section with subclass-based architecture, update removal conditions
- [x] 9.4 Verify no other files import from `httpcore_patch`

## 10. Quality Checks

- [x] 10.1 Run `poetry run pyright` — must pass with zero errors
- [x] 10.2 Run `poetry run ruff check src/ tests/` — must pass
- [x] 10.3 Run `poetry run black src/ tests/` — must produce no changes

## 11. Testing

- [x] 11.1 Read `test-plan.md` Delegation Groups section
- [x] 11.2 Delegate group `core-http2-unit` to @Mr.Tester (scope: `tests/unit/core/http2/`)
- [x] 11.3 Delegate group `stress-tests-regression` to @Mr.Tester (scope: `tests/stress/`)
- [x] 11.4 Delegate group `integration-tests` to @Mr.Tester (scope: `tests/unit/core/test_http_client_factory.py`, `tests/integration/`)
- [x] 11.5 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 11.6 Re-delegate any groups affected by source fixes
- [x] 11.7 Verify all groups pass and coverage matches `test-plan.md`
- [x] 11.8 Run full test suite: `poetry run pytest tests/ -v`
- [x] 11.9 Run full test suite with coverage: `poetry run pytest --cov=src tests/`

## 12. Documentation

- [x] 12.1 Create `src/core/http2/README.md` with: why this exists, what each class does, when to remove
