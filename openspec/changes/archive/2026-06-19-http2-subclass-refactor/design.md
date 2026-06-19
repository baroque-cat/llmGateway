## Context

The llmGateway project manages LLM provider API keys through two runtime components: Keeper (background health monitoring) and Conductor (FastAPI gateway). Both use `httpx.AsyncClient` with HTTP/2 enabled (`http2: true`) to communicate with upstream provider APIs (DeepSeek, Anthropic, OpenAI-compatible, Gemini).

**Current state:** A monkey-patch at `src/core/httpcore_patch.py` (357 lines) fixes two upstream httpcore bugs by directly replacing methods on `AsyncHTTP2Connection`, `HTTP2Connection`, `AsyncSemaphore`, and `Semaphore` classes. The patch is applied once at module level in `main.py:23` and `tests/stress/conftest.py:19`.

**Why refactor:** The monkey-patch violates the project's architectural principles — the codebase uses `I`-prefixed abstract base classes (`IProvider`, `IResourceProbe`, `IResourceSyncer`, etc.), polymorphism via Strategy/Template Method patterns, and manual dependency injection through constructors. Monkey-patching (replacing methods on third-party classes) is the opposite of these patterns. Additionally, the current patch cannot implement the full PR #1088 architecture because monkey-patching cannot add new constructor parameters (`on_capacity_update`) or new methods on interfaces.

**Constraint:** httpcore 1.0.9 creates `AsyncSemaphore` inside `handle_async_request()` in the `_init_lock` block, not in `__init__`. This architectural defect in httpcore prevents clean method-level override of the semaphore creation — we cannot replace the semaphore type without replacing the entire method. This is the one place where our subclass must duplicate code, with explicit documentation of the reason.

**Reference:** Full analysis in `docs/HTTP2_REFACTOR_PLAN.md`. Upstream PRs: [httpcore#1022](https://github.com/encode/httpcore/issues/1022) (stream desync), [httpcore#1088](https://github.com/encode/httpcore/pull/1088) (connection growth).

## Goals / Non-Goals

**Goals:**
1. Replace monkey-patch with subclass-based architecture that matches project's polymorphism + DI patterns
2. Implement full PR #1088 mechanics: `on_capacity_update` callback, `acquire_nowait()`, `connection_request_count`, `_closed_streams` tracking, conditional semaphore release
3. Integrate at single point (`HttpClientFactory`) via httpx's `transport=` parameter
4. Make each component independently testable with unit tests
5. Freeze dependency versions explicitly to prevent silent breakage
6. Remove the old monkey-patch file entirely

**Non-Goals:**
- Fork httpcore — we use subclassing, not modifying httpcore source
- Change httpx or httpcore public API — our transport is a drop-in replacement
- Modify provider adapters or gateway dispatch logic
- Add HTTP/2 toggles per-provider (remains global)
- Implement sync `HTTP2Connection` fix for Bug #2 Layer 3 (project is fully async)
- Support SOCKS/HTTP proxy connections in `CapacityAwareHttp2Transport` (project doesn't use httpcore-level proxies)
- Change stress test assertions or scenarios

## Decisions

### Decision 1: Two-layer transport architecture (pool + httpx wrapper)

**Chosen:** Create `CapacityAwareHttp2Pool(AsyncConnectionPool)` for the capacity-aware routing logic, and `CapacityAwareHttp2Transport(httpx.AsyncHTTPTransport)` as a thin httpx-compatible wrapper that passes the pool as `transport=` to `httpx.AsyncClient`.

**Why two layers:** `httpx.AsyncClient._send_single_request()` expects the transport's `handle_async_request()` to accept `httpx.Request` and return `httpx.Response` (with `AsyncResponseStream`). Passing an `AsyncConnectionPool` subclass directly causes `AssertionError` — httpx requires an `httpx.AsyncHTTPTransport` subclass to correctly convert between `httpx.Request` ↔ `httpcore.Request` and `httpcore.Response.stream` ↔ `AsyncResponseStream`. The wrapper inherits all conversion logic from `httpx.AsyncHTTPTransport` while delegating pool management to our `CapacityAwareHttp2Pool`.

**Alternatives considered:**
- *Keep monkey-patching* — already known to violate project patterns, cannot implement full PR #1088
- *Fork httpcore and apply PR #1088 directly* — cleaner result but requires maintaining fork, updating on each httpcore release
- *Subclass AsyncConnectionPool directly as transport=* — tried and failed: `AssertionError` in `httpx._client._send_single_request` because `AsyncResponseStream` wrapping was missing
- *Add middleware at httpx level* — httpx middleware can't intercept connection pool routing decisions

### Decision 2: `FixedHTTP2Connection` copies `handle_async_request` with documented change

**Chosen:** Override `handle_async_request` with a copy of the httpcore 1.0.9 method, changing exactly one section: `acquire()` → `acquire_nowait()` with state rollback on failure. Other overrides (`_response_closed`, `is_available`, `_receive_events`, `_receive_remote_settings_change`) are clean partial overrides.

**Alternatives considered:**
- *Create semaphore in `__init__` instead* — cannot because `_max_streams` and `local_settings_max_streams` are only known after connection init which happens inside `handle_async_request`
- *Extract semaphore creation to a protected method* — would require modifying httpcore source (not just subclassing)
- *Use `NonBlockingSemaphore` with a factory callback* — httpcore has no hook for semaphore factory injection

**Rationale:** The only alternative that avoids copying the method is modifying httpcore source (fork). The copied method is clearly documented with its origin, and the single change point is marked with an obvious comment block. This is the least-bad option given httpcore's architecture. When httpcore merges PR #1088, the entire `FixedHTTP2Connection` class (including the copied method) becomes obsolete and is removed.

### Decision 3: Package structure: one class per file

**Chosen:** `src/core/http2/` with 6 files — `__init__.py`, `semaphore.py`, `h2_connection.py`, `connection.py`, `pool.py`, `transport.py`.

**Rationale:** One class per file follows the project's existing pattern. Each component can be tested independently. The dependency chain is clear: `semaphore.py` has no internal deps → `h2_connection.py` depends on `semaphore.py` → `connection.py` depends on `h2_connection.py` → `pool.py` depends on `connection.py` → `transport.py` depends on `pool.py`.

### Decision 4: Integration at `HttpClientFactory` only

**Chosen:** Create `CapacityAwareHttp2Transport` inside `HttpClientFactory.get_client_for_provider()` and pass as `transport=`.

**Alternatives considered:**
- *Apply at `main.py` module level* (like current monkey-patch) — hidden, violates DI pattern, hard to test
- *Create transport in a separate factory* — adds unnecessary indirection for a single transport implementation
- *Make it configurable* — no use case; we always want the fix applied

**Rationale:** `HttpClientFactory` is the sole creation point for `httpx.AsyncClient` (confirmed via codebase exploration). Integrating here keeps the change local, follows DI pattern (transport is injected), and is easy to remove (remove 2 lines).

### Decision 5: Explicit dependency pinning

**Chosen:** Add `httpcore = "1.0.9"` and `h2 = ">=4.3.0,<5.0"` to `pyproject.toml` `[project.dependencies]`. Add CI version check.

**Alternatives considered:**
- *Rely on transitive pins only* — httpx 0.28.1 pins `httpcore==1.*` which resolves to 1.0.9 today, but could resolve to 1.1.x if httpx loosens
- *Only pin in lockfile* — lockfile pins are ignored by some tools; explicit constraints are safer

**Rationale:** Explicit pins serve as documentation and prevent silent upgrade. The CI check catches version drift. Both `poetry.lock` and `uv.lock` are frozen.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **httpcore upgrade breaks subclass** — if httpcore changes `handle_async_request` or `_assign_requests_to_connections` internals, our overrides may break | Version frozen in pyproject.toml + CI version check. httpcore rarely releases breaking changes. |
| **`FixedHTTP2Connection.handle_async_request` goes stale** — the copied method won't include httpcore bugfixes | Version guard; documented as "remove when PR #1088 merges." httpcore 1.0.x is stable — no bugfix releases since 1.0.9 (Apr 2025). |
| **`uv.lock` and `poetry.lock` diverge** — two lockfiles could resolve different httpcore versions | Both currently resolve 1.0.9; explicit `pyproject.toml` pin prevents divergence |
| **Stress test timing changes** — subclass-based architecture might have slightly different timing characteristics than monkey-patch | Stress test assertions use ranges (e.g., `pool_timeout_errors > 0`, `connections_created >= 2`), not exact values. Run full suite before and after. |
| **`CapacityAwareHttp2Transport` incompatible with proxy configs** — `create_connection()` in PR #1088 changed proxy creation paths | Project's proxy config uses httpx-level `proxy=` parameter, not httpcore-level proxy connections. No risk. |
| **`_closed_streams` approach more complex than current Bug #1 fix** — PR #1088 uses server-close tracking vs current simple check | Follow PR #1088 exactly; the approach is proven by upstream tests. More accurate (avoids unnecessary RST_STREAM). |

## Migration Plan

1. **Freeze dependencies** — add explicit pins to `pyproject.toml`, verify both lockfiles
2. **Create package** — build `src/core/http2/` with all 5 files
3. **Integrate** — modify `HttpClientFactory` to use `CapacityAwareHttp2Transport`
4. **Remove old code** — delete `httpcore_patch.py`, remove `apply_patch()` calls, delete `test_stream_desync_patch.py`
5. **Verify** — run all 18 stress tests, pyright, ruff, black
6. **Commit** — single atomic commit with the migration

**Rollback:** Revert commit. The old monkey-patch and the new subclass-based transport have identical behavior — stress tests pass with both. No data migration, no config changes.

## Open Questions

- (none — design is complete based on PR #1088 diff and project architecture analysis)
