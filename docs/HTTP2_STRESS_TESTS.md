# HTTP/2 Monkey-Patches & Stress Test Suite

This document describes two production HTTP/2 bugs in `httpcore`/`httpx`,
the monkey-patches that fix them, the stress test suite that validates
the fixes, and the known limitations of the partial backports.

## Table of Contents

1. [Production Problem](#1-production-problem)
2. [Root Causes](#2-root-causes)
   - [2.1 Bug #1: Stream Desync (httpcore#1022)](#21-bug-1-stream-desync-httpcore1022)
   - [2.2 Bug #2: Connection Growth (httpcore#1088)](#22-bug-2-connection-growth-httpcore1088)
3. [The Monkey-Patches](#3-the-monkey-patches)
   - [3.1 Patch #1: Stream Desync](#31-patch-1-stream-desync)
   - [3.2 Patch #2: Connection Growth](#32-patch-2-connection-growth)
   - [3.3 Safety Properties](#33-safety-properties)
4. [Stress Test Suite](#4-stress-test-suite)
   - [4.1 Infrastructure](#41-infrastructure)
   - [4.2 Desync Patch Test](#42-desync-patch-test)
   - [4.3 Connection Growth Tests](#43-connection-growth-tests)
   - [4.4 Other Tests](#44-other-tests)
   - [4.5 Proving the Patches Work](#45-proving-the-patches-work)
5. [What the Patches CAN and CANNOT Do](#5-what-the-patches-can-and-cannot-do)
6. [Patch Architecture](#6-patch-architecture)
7. [Related Links](#7-related-links)
8. [When to Remove the Patches](#8-when-to-remove-the-patches)

---

## 1. Production Problem

Under high concurrency (multi-agent workloads with 10+ simultaneous
agents), the Gateway experienced cascading failures against the
DeepSeek API:

```
ERROR | provider | Upstream network error: [LocalProtocolError]
  provider='deepseek-home' — Max outbound streams is 128, 128 open
```

**Symptoms:**

- Requests timed out after 600 s (`asyncio.timeout` in the retry loop).
- After timeout, subsequent requests failed with `LocalProtocolError:
  Max outbound streams is 128, 128 open`.
- The Gateway's retry logic classified `LocalProtocolError` as
  `ErrorReason.NETWORK_ERROR`, which is `is_retryable() == True` and
  `is_server_error() == True`.
- Server retries (3 attempts per key) all failed identically.
- Each retry exhaustion penalised the key (`status = "network_error"`,
  cooldown applied).
- The Gateway rotated through **~50 keys** — all penalised — before
  the service was restarted.
- **None of the keys were actually bad.**  The failure was a local
  infrastructure bug.

Two separate bugs in httpcore combine to cause this:

| Bug | Upstream Issue | Effect |
| --- | --- | --- |
| Stream Desync | [httpcore#1022](https://github.com/encode/httpcore/issues/1022) | Cancelled streams are never cleaned up in h2's state → phantom slots → `NoAvailableStreamIDError` |
| Connection Growth | [httpcore#1088](https://github.com/encode/httpcore/pull/1088) | Pool never opens new TCP connections when existing H2 connections are full → all requests pile onto one connection |

---

## 2. Root Causes

### 2.1 Bug #1: Stream Desync (httpcore#1022)

`httpcore` uses two **independent** mechanisms to track open HTTP/2 streams:

| Mechanism | Where | Purpose |
| --- | --- | --- |
| `_max_streams_semaphore` | `httpcore._async.http2` | Enforces `SETTINGS_MAX_CONCURRENT_STREAMS` client-side |
| `open_outbound_streams` | `h2.connection.H2Connection` | h2 library's internal counter (computed property) |

When an asyncio task is cancelled (e.g. by `asyncio.timeout(600)` in
the Gateway retry loop), httpcore's `except BaseException` handler
calls `_response_closed(stream_id)`.  This method **releases the
semaphore** — but it never notifies h2 that the stream is closed.

Result:

```
httpcore semaphore:       "slot free, can open another stream"
h2 open_outbound_streams: "128 streams open, cannot open more"
→ NoAvailableStreamIDError → LocalProtocolError
```

#### Why retry makes it worse

Every retry opens a new stream on the same connection.  Without the
patch, cancelled streams are never cleaned up in h2's state, so every
retry inches closer to the `open_outbound_streams` limit.  Once the
limit is reached, ALL subsequent requests fail with the same
`LocalProtocolError`, regardless of which key is used.

The Gateway's retry logic then penalises key after key — a
**self-reinforcing cascade** that burns through the entire key pool.

#### What the fix does

The patched `_response_closed()` checks whether the stream is still
open in h2's state.  If the stream exists and is not closed (headers
were sent), it calls `h2_state.reset_stream()` to send `RST_STREAM`
and mark the stream closed.

If no stream object exists (cancelled before `send_headers`), h2 never
counted it — no cleanup is needed.  `open_outbound_streams` in h2 4.x
is a read-only computed property that reflects actual stream state; a
phantom stream ID that was never sent doesn't contribute to it.

```python
# src/core/httpcore_patch.py — the fix (14 lines of logic)
stream = self._h2_state.streams.get(stream_id)
if stream is not None and not stream.closed:
    self._h2_state.reset_stream(stream_id)
# Then: original _response_closed (semaphore release, event cleanup)
```

### 2.2 Bug #2: Connection Growth (httpcore#1088)

httpcore's connection pool selects a connection for each request by
checking `is_available()`.  For H2 connections, `is_available()` only
checks the connection state (ACTIVE/IDLE/CLOSED) — it does **not**
check whether the connection has room for another H2 stream.

When a connection's H2 streams are all occupied:

1. `is_available()` returns `True` — pool sees the connection as "free"
2. Pool assigns the request to the same connection
3. `handle_async_request()` calls `semaphore.acquire()` — **blocks
   indefinitely** waiting for a stream slot
4. Request hangs until `pool_timeout` (30 seconds in tests) or until
   another request completes and frees a slot

The pool **never opens new TCP connections** because it doesn't know
the existing ones are full.  This is especially harmful at concurrency
levels where the H2 stream limit is the bottleneck, not the number of
TCP connections.

#### Upstream fix (PR #1088)

The full fix in [encode/httpcore#1088](https://github.com/encode/httpcore/pull/1088)
involves changes in ~14 files and introduces `on_capacity_update`
callbacks, `acquire_nowait()` on semaphores, and `max_concurrent_requests()`
on the connection interface.

#### Our partial backport

Our monkey-patch implements the **core mechanics** of PR #1088 in three
layers (detailed in §3.2).  It omits the `on_capacity_update` callback
infrastructure because that requires changes in too many files for a
safe monkey-patch.

---

## 3. The Monkey-Patches

**File:** `src/core/httpcore_patch.py` (357 lines)

**Applied in:** `main.py` (module-level, before any `httpx.AsyncClient`
is created) and `tests/stress/conftest.py` (for stress tests).

**Public API:** `apply_patch()` — applies all patches.  Safe to call
multiple times (idempotent).

### 3.1 Patch #1: Stream Desync

Replaces `_response_closed()` on `AsyncHTTP2Connection` (async) and
`HTTP2Connection` (sync).  Before releasing the semaphore, the patched
method synchronises h2's stream state.

**Version-sensitive import.** The patch captures references to the
original methods at apply-time, so it works against the installed
httpcore version regardless of how the methods are implemented:

```python
async_original = AsyncHTTP2Connection._response_closed
sync_original = HTTP2Connection._response_closed
patched_async, patched_sync = _make_patched_response_closed(
    async_original, sync_original
)
AsyncHTTP2Connection._response_closed = patched_async
HTTP2Connection._response_closed = patched_sync
```

**No impact on normal operation.** When streams close normally
(no cancellation), `stream.closed` is already `True` — the
`reset_stream()` call is skipped.

**Guard:** `_stream_desync_patched` module-level flag.

### 3.2 Patch #2: Connection Growth

Three sub-patches that work together.  Each is applied independently
with its own guard.

#### Layer 1: Semaphore `.available` property

Adds a read-only `.available` property to `AsyncSemaphore` and
`Semaphore` that exposes the number of remaining acquire slots.

```python
# Async: delegates to anyio.Semaphore.value or trio.Semaphore.value
AsyncSemaphore.available = property(_async_available)

# Sync: delegates to threading.Semaphore._value
Semaphore.available = property(_sync_available)
```

Without this, the pool cannot query whether a connection has room for
another stream.

**Guard:** checks `hasattr(AsyncSemaphore, "available")`.

#### Layer 2: Stream-aware `is_available()`

Replaces `is_available()` on `AsyncHTTP2Connection` and
`HTTP2Connection`.  The patched version first calls the original
(state, error, and stream-ID checks), then additionally verifies
that the connection has free H2 streams:

```python
def _async_is_available(self):
    if not _async_orig(self):           # original checks
        return False
    sem = getattr(self, "_max_streams_semaphore", None)
    return sem is None or sem.available is None or sem.available > 0
    #     ↑ no semaphore       ↑ not yet initialised   ↑ has free streams
```

When `is_available()` returns `False`, the pool skips this connection
and either picks another or opens a new one.

**Guard:** `__httpcore_capacity_aware__` marker on the function.

#### Layer 3: Non-blocking semaphore in `handle_async_request`

This is the most invasive patch — it replaces the entire
`handle_async_request` method on `AsyncHTTP2Connection` (~120 lines).
The only functional change is on **one line** — the semaphore acquire:

```python
# ORIGINAL (httpcore 1.0.9, line 131):
await self._max_streams_semaphore.acquire()
# ↑ Blocks forever when all streams are occupied

# PATCHED (line 249):
if self._max_streams_semaphore.available <= 0:
    self._request_count -= 1           # roll back the increment from state_lock
    raise ConnectionNotAvailable()     # signal pool: "I'm full, try another"
await self._max_streams_semaphore.acquire()
```

The method had to be replaced in its entirety because the semaphore
is created inside `handle_async_request` (in the `_init_lock` block),
not in `__init__`.  There is no way to intercept the semaphore creation
without replacing the whole method.

**Why `_request_count -= 1` is needed.**  The method increments
`_request_count` in the `_state_lock` block (line 217 of the patched
code) before reaching the semaphore check.  If the request is sent
back to the pool (via `ConnectionNotAvailable`), the count must be
rolled back to keep the connection's state consistent.

**How the pool reacts.**  The pool's `handle_async_request` catches
`ConnectionNotAvailable` and re-queues the request:

```python
# connection_pool.py, line 234-244
try:
    response = await connection.handle_async_request(request)
except ConnectionNotAvailable:
    pool_request.clear_connection()    # unassign from this connection
    # loop back → _assign_requests_to_connections()
    # → is_available() (Layer 2) returns False for full connections
    # → pool opens a new TCP connection
```

**Guard:** `__httpcore_nonblocking__` marker on the function.

### 3.3 Safety Properties

- **Idempotent** — each sub-patch checks its own guard (module flag
  or function marker); `apply_patch()` is safe to call multiple times.
- **Version guard** — logs a warning if `httpcore.__version__` ≠
  `1.0.9` (the tested version).  Serves as a reminder to re-evaluate
  after dependency upgrades.
- **Zero impact in normal operation** — Patch #1 checks `stream.closed`
  before `reset_stream()`.  Patch #2 Layer 2 checks `sem is None` for
  unestablished connections.  Layer 3 checks `available <= 0` only
  after the semaphore is initialised.
- **Independent guards** — `_stream_desync_patched` and
  `_connection_growth_patched` are separate; one patch can be removed
  without affecting the other.
- **Graceful degradation** — if any patch fails to apply (e.g. due to
  httpcore version mismatch), the remaining patches still attempt to
  apply.  The version warning is non-fatal.
- **Removable** — delete `src/core/httpcore_patch.py` and the two
  `apply_patch()` calls.  No other files depend on the patch internals.

### 3.4 Why monkey-patch instead of forking httpcore

- The fix logic is ~40 lines total — a fork would be overkill.
- The patch lives in the project's git history and survives
  `poetry install` / dependency updates.
- The version guard warns on httpcore upgrade so the patch can be
  re-evaluated.
- The patch is self-contained in one file with no new dependencies.

---

## 4. Stress Test Suite

**Location:** `tests/stress/` — 18 tests, all marked `pytest.mark.slow`.

All tests use a **real network stack** — TLS handshakes, HTTP/2
negotiation via the `h2` library, and actual `httpx`/`httpcore`
clients.  No mocks.

### 4.1 Infrastructure

| Component | File | Purpose |
| --- | --- | --- |
| Ephemeral HTTP/2 server | `tests/stress/ephemeral_api.py` | Configurable H2-over-TLS server with stream limits, response delays, and live metrics |
| Metrics collector | `tests/stress/metrics.py` | Aggregates server-side counters, httpx trace events, error classification, and latency percentiles |
| Fixtures | `tests/stress/conftest.py` | Session-scoped server factory, convenience fixtures (`fast_server`, `slow_server`) |

The ephemeral server is created per-test via `http2_server_factory` and
automatically destroyed at session end.  It supports:

- `max_concurrent_streams` — server-advertised stream limit
- `response_delay_ms` — artificial response delay
- Live metrics: peak connections, peak streams, total connections

### 4.2 Desync Patch Test (`test_stream_desync_patch.py`)

This is the **primary validation** of Patch #1.  It uses raw `httpcore`
(not `httpx`) because httpx 0.28.1 catches `CancelledError` at its own
level and properly closes streams, masking the desync bug.  The
production path goes through the Gateway's `asyncio.timeout()`, which
cancels httpcore tasks directly.

**Scenario:**

1. Start ephemeral server with `max_concurrent_streams = 30` and a
   30-second response delay (server never responds during the test).
2. Open 25 concurrent POST requests with 4 KB bodies on a
   single-connection pool.
3. Cancel all 25 tasks after 150 ms (mass cancellation).
4. Wait 500 ms for `_response_closed` to run.
5. Send **10** follow-up GET requests on the **same** pool.

**Results:**

| | Without patch | With patch |
| --- | --- | --- |
| Follow-up successes | 5 / 10 | **10 / 10** |
| Follow-up failures | 5 `LocalProtocolError` | **0** |
| Root cause | `open_outbound_streams` still counts 25 phantom streams after cancellation → 25 + 10 = 35 > 30 limit | Cancelled streams properly cleaned up → `open_outbound_streams = 0` after cancellation → 10 < 30 limit |

**How to run with and without the patch:**

```bash
# With patch (default — main.py and conftest.py both call apply_patch())
poetry run pytest tests/stress/test_stream_desync_patch.py -v
# → 10/10 successes, PASSED

# Without patch (comment out apply_patch() in main.py and conftest.py)
poetry run pytest tests/stress/test_stream_desync_patch.py -v
# → 5/10 successes + 5 LocalProtocolError, FAILED
```

### 4.3 Connection Growth Tests

Two tests validate Patch #2.  Both were previously marked
`@pytest.mark.xfail(strict=True)` and are now passing.

#### `test_six_connections_for_thirty_requests` (test_connection_growth.py)

**Setup:** 30 concurrent GETs, server `max_concurrent_streams=5`,
server delay 2 s, client `max_connections=10`, pool timeout 30 s.

**What it proves:**

| Assertion | Before patch | After patch | Why it matters |
| --- | --- | --- | --- |
| `connections_created >= 2` | 1 ❌ | **3 ✅** | Pool opens multiple TCP connections |
| `success_count > 5` | 5 ❌ | **11 ✅** | Requests distributed across connections (1 connection can't serve > 5 streams) |
| `local_protocol_errors < 30` | 25 ❌ | **19 ✅** | Most requests complete or timeout cleanly |

#### `test_pool_exhausted_with_long_responses` (test_pool_saturation.py)

**Setup:** 20 concurrent GETs, server `max_concurrent_streams=1`,
server delay 10 s, client `max_connections=3`, pool timeout 5 s.

**What it proves:**

| Assertion | Before patch | After patch | Why it matters |
| --- | --- | --- | --- |
| `pool_timeout_errors > 0` | **0** ❌ | **4 ✅** | Pool timeout mechanism WORKS for H2 |
| `success_count <= 3` | 1 ✅ | **3 ✅** | One success per connection (all busy for 10 s) |
| `local_protocol_errors < 20` | 19 ✅ | **13 ✅** | Residual protocol errors during connection cycling (acceptable) |

**Key improvement:** Before the patch, `pool_timeout_errors` was
always 0 — requests hung indefinitely on the semaphore and never
reached the pool timeout.  With the patch, 4 requests correctly
time out after 5 s, proving the pool's timeout mechanism now works
for HTTP/2 connections.

### 4.4 Other Tests

| Test | What it verifies |
| --- | --- |
| `test_stream_exhaustion.py` | httpx correctly surfaces stream-limit errors |
| `test_pool_recovery.py` | Connection pool self-recovers after a load spike subsides (Phase 1: 50 concurrent → Phase 2: 5 sequential after 30 s cooldown) |
| `test_keepalive_churn.py` | `keepalive_expiry = 5 s` forces new TCP connections when requests are spaced > 5 s apart |
| `test_multi_client.py` | Two independent `httpx.AsyncClient` instances maintain separate connection pools |
| `test_ephemeral_server.py` | 6 tests: server startup, single request, clean shutdown, response delay, concurrent metrics, peak stream tracking |
| `test_metrics_collector.py` | MetricsCollector correctness: trace events, error classification, OS TCP stats |

### 4.5 Proving the Patches Work

```bash
# Run the full stress suite
poetry run pytest tests/stress/ -v

# Run only specific patches
poetry run pytest tests/stress/test_stream_desync_patch.py -v
poetry run pytest tests/stress/test_connection_growth.py -v
poetry run pytest tests/stress/test_pool_saturation.py -v

# Skip slow tests (if marker configured in pyproject.toml)
poetry run pytest tests/stress/ -v -m "not slow"
```

**Current status: 18/18 PASS** (all tests pass with both patches applied).

---

## 5. What the Patches CAN and CANNOT Do

### CAN ✅

| Capability | Patch | Evidence |
| --- | --- | --- |
| Clean up h2 stream state after asyncio cancellation | #1 | `test_stream_desync_patch`: 10/10 follow-ups succeed (was 5/10) |
| Prevent phantom stream accumulation in h2 | #1 | After 25 cancellations, h2 correctly reports 0 open streams |
| Open multiple TCP connections for H2 | #2 | `test_connection_growth`: 3 connections (was 1) |
| Distribute requests across connections | #2 | 11 successes with `max_streams=5` proves cross-connection routing |
| Raise `PoolTimeout` for H2 connections | #2 | `test_pool_saturation`: 4 pool timeouts (was 0) |
| Operate transparently — no API changes | Both | Same `httpx.AsyncClient` usage, same config |
| Survive dependency updates | Both | Version guard warns; patch is self-contained |

### CANNOT ❌

| Limitation | Reason | Impact |
| --- | --- | --- |
| Achieve theoretical max concurrency (6 connections for 30 reqs × 5 streams) | Missing `on_capacity_update` callback from PR #1088 — pool only learns about freed streams on the next `while` iteration | In tests: 3 connections instead of 6. In production at 128 streams × 100 connections: negligible. |
| Eliminate all `LocalProtocolError` during connection cycling | Connections being closed while requests are in-flight produce protocol errors that the pool doesn't retry | In tests: ~13 local_protocol_errors in saturation scenario. In production with `stream_limit=128`: rare. |
| Handle sync `HTTP2Connection` for Bug #2 | Only the async `handle_async_request` is patched (the project is fully async; sync path is only used in tests) | No impact on production. Sync tests use Bug #1 patch only. |
| Survive a major httpcore refactor | The Layer 3 patch replaces the entire `handle_async_request` method — if the upstream method changes significantly, the patch must be rewritten | Mitigated by the version guard warning on httpcore upgrade. |

### Production Impact Assessment

At production stream limits (128 streams × 100 connections for
DeepSeek), the theoretical maximum concurrency is 12,800 concurrent
streams.  The Gateway's real-world concurrency is 10-50 simultaneous
agents, each issuing sequential requests.  In this regime:

- **Bug #1 fix is critical** — even 5 cancellations without the fix
  would create phantom streams that accumulate over the lifetime of
  a connection.
- **Bug #2 fix is beneficial** — with 128 streams per connection, a
  single connection can handle all normal load.  But under burst or
  when streams are slow to free, the non-blocking semaphore prevents
  request pile-up.

The patch's limitations (fewer connections than theoretical max,
residual `LocalProtocolError`) have **zero practical impact** at
production stream limits.

---

## 6. Patch Architecture

```
src/core/httpcore_patch.py  (357 lines)
│
├─ apply_patch()  ← called in main.py and tests/stress/conftest.py
│  ├─ version guard: httpcore == 1.0.9 (warning if mismatch)
│  │
│  ├─ _apply_stream_desync_fix()                    ← Patch #1
│  │  └─ replaces _response_closed on:
│  │     ├─ AsyncHTTP2Connection (async)
│  │     └─ HTTP2Connection (sync)
│  │     Logic: reset_stream(h2) → original method
│  │     Guard: _stream_desync_patched
│  │
│  └─ _apply_connection_growth_fix()                ← Patch #2
│     ├─ _add_semaphore_available_property()
│     │  ├─ AsyncSemaphore.available → anyio.Semaphore.value
│     │  └─ Semaphore.available → threading.Semaphore._value
│     │  Guard: hasattr(AsyncSemaphore, "available")
│     │
│     ├─ _patch_h2_is_available()
│     │  ├─ AsyncHTTP2Connection.is_available() → +check sem.available > 0
│     │  └─ HTTP2Connection.is_available() → +check sem.available > 0
│     │  Guard: __httpcore_capacity_aware__ marker
│     │
│     └─ _patch_h2_nonblocking_semaphore()
│        └─ AsyncHTTP2Connection.handle_async_request
│           Replaces blocking semaphore.acquire() with:
│             if available <= 0: raise ConnectionNotAvailable()
│           Guard: __httpcore_nonblocking__ marker
│
└─ Guard: _connection_growth_patched
```

**Call sites:**

```
main.py (line 23)
  │
  └─ apply_patch()  ← runs at module level, before load_config()
                      ensures patch is active before any httpx client
                      is created by the Gateway or Keeper

tests/stress/conftest.py (line 19)
  │
  └─ apply_patch()  ← runs at module level, before any fixture
                      creates httpx clients for stress tests
```

---

## 7. Related Links

| Link | Description |
| --- | --- |
| [encode/httpcore#1022](https://github.com/encode/httpcore/issues/1022) | Upstream Bug #1 — stream desync (open, unfixed as of Jun 2026) |
| [encode/httpcore#1088](https://github.com/encode/httpcore/pull/1088) | Upstream PR for Bug #2 — connection growth (open, unfixed as of Jun 2026) |
| [darshvn/httpcore#1](https://github.com/darshvn/httpcore/pull/1) | Fork with an earlier version of the Bug #1 fix |
| [httpx HTTP/2 docs](https://www.python-httpx.org/http2/) | HTTP/2 is explicitly described as "less robust than HTTP/1.1" |

---

## 8. When to Remove the Patches

Remove `src/core/httpcore_patch.py` and the two `apply_patch()` calls
(from `main.py` and `tests/stress/conftest.py`) when **either**:

1. `encode/httpcore` merges fixes for **both** #1022 and #1088, and
   the project upgrades to that version.
2. The project migrates away from HTTP/2 (`http2: false` in
   `http_client` config) for all providers.

The version guard logs a warning on httpcore upgrade, serving as a
reminder to re-evaluate the patches.
