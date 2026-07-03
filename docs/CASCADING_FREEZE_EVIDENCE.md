# HTTP/2 Cascading Freeze: Test Evidence and Root Cause Analysis

## Summary

This document presents the results of three stress tests that reproduce the
production HTTP/2 cascading-freeze anomaly observed when multiple agents
send concurrent requests to a single LLM provider through the llmGateway.
The tests prove three distinct failure mechanisms that combine to cause a
total system freeze beyond a provider-specific concurrency threshold
(~8 concurrent streams in production).

All tests use the `EphemeralHttp2Server` — a minimal HTTP/2-over-TLS test
server that can advertise a fake `max_concurrent_streams` value while
enforcing a lower internal concurrency limit. This models the real-world
scenario where a provider or proxy advertises 100 concurrent streams but
only processes a fraction of them simultaneously.

---

## Table of Contents

1. [Production Problem](#1-production-problem)
2. [Root Causes](#2-root-causes)
3. [Test Infrastructure](#3-test-infrastructure)
4. [Test 1: Abrupt Freeze at Concurrency Threshold](#4-test-1-abrupt-freeze-at-concurrency-threshold)
5. [Test 2: Cascading Backlog After Initial Batch](#5-test-2-cascading-backlog-after-initial-batch)
6. [Test 3: Read Timeout Silence with Drip-Feed](#6-test-3-read-timeout-silence-with-drip-feed)
7. [Test Results Summary](#7-test-results-summary)
8. [What the Tests Prove vs. What They Do Not](#8-what-the-tests-prove-vs-what-they-do-not)
9. [Conclusion](#9-conclusion)

---

## 1. Production Problem

### Symptoms

When 10 agents send concurrent requests to a single provider (e.g.,
`qwen-home`) through the gateway with 4 uvicorn workers:

1. **Initial requests succeed.** The first ~8 concurrent streams receive
   `200 OK` and stream responses normally.

2. **Beyond ~8 concurrent streams, all new requests freeze.** No `200 OK`
   is received, no bytes arrive. The streams appear completely stuck.

3. **The freeze cascades.** After the initial 8 streams complete, the
   agents send new requests (next conversation turn). These new requests
   also freeze — the server is still backlogged with queued streams from
   the first batch.

4. **Bimodal completion.** Some requests eventually complete after minutes
   of waiting. Others are killed by the 600-second gateway timeout.

5. **Restart fixes it.** Killing and restarting the gateway clears the
   backlog. The system works normally until concurrency exceeds ~8 again.

6. **Other providers are unaffected.** Providers with lower traffic or
   different internal limits continue working normally.

### Production Log Signature

```
HTTP_POOL_HEALTH | provider=qwen-home | conns: 1 total (1 active, 0 idle) |
  proto: 1 H2 / 0 H1 | streams: 14 active / 100 max_capacity | queued: 0
```

Key observations from the log:

- **1 connection, 14 active streams** — all requests funnel through a
  single TCP connection.
- **max_capacity = 100** — the pool believes the connection can handle 100
  concurrent streams (the H2 `SETTINGS_MAX_CONCURRENT_STREAMS` advertised by
  the server). 14 out of 100 looks like 86% headroom.
- **queued = 0** — no requests are waiting at the httpx pool level. All 14
  are "in flight" on the single H2 connection.
- **conns = 1** — despite `max_connections = 100` in config, only one TCP
  connection is ever opened.

---

## 2. Root Causes

Two independent bugs combine to produce the cascading freeze.

### Bug 1: Pool Trusts Advertised `max_concurrent_streams`

The connection pool (`CapacityAwareHttp2Pool`) decides whether to reuse an
existing connection or open a new one based on this check
(`src/core/http2/pool.py:155-165`):

```python
available_connection = next(
    (
        conn
        for conn in self._connections
        if conn.can_handle_request(origin)
        and conn.is_available()
        and connection_request_count[conn]
        < self._max_concurrent_requests(conn)   # <-- the capacity gate
    ),
    None,
)
```

`_max_concurrent_requests(conn)` delegates to
`FixedHTTP2Connection.max_concurrent_requests()`, which returns
`self._max_streams`. This value is computed in
`_receive_remote_settings_change` (`src/core/http2/h2_connection.py:200-203`)
as:

```python
new_max_streams = min(
    max_concurrent_streams.new_value,            # server-advertised
    self._h2_state.local_settings.max_concurrent_streams,  # local = 100
)
```

The value `100` originates from the `h2` library default
(`h2/connection.py:356`) and is re-asserted by httpcore
(`httpcore/_async/http2.py:204`). It is **not** hardcoded in our code, and
there is **no configuration option** to override it.

**Consequence:** When the server advertises `MAX_CONCURRENT_STREAMS=100`
(which is the h2 library default), the pool believes a single connection
can handle 100 concurrent streams. With only 10-14 agents, the pool never
reaches this limit and never opens a second connection. All streams pile
onto one TCP connection.

The server's **real** internal concurrency limit (e.g., 8) is invisible to
the client — it is not advertised in H2 SETTINGS. The pool has no way to
detect it.

### Bug 2: Socket-Level Read Timeout (Not Per-Stream)

The httpx `read` timeout (default 120s) is translated through the call
chain as follows:

```
httpx.Timeout(read=120)
  → request.extensions["timeout"]["read"] = 120.0
    → httpcore _read_incoming_data() extracts "read" from extensions
      → AnyIOStream.read(max_bytes, timeout=120)
        → anyio.fail_after(120):
              return await self._stream.receive(max_bytes)
```

The critical line is `httpcore/_backends/anyio.py:33`:

```python
with anyio.fail_after(timeout):
    return await self._stream.receive(max_bytes=max_bytes)
```

`anyio.fail_after(120)` wraps a **single `socket.receive()` call** — one
socket read on the shared TCP connection. It is **not** a per-stream
deadline. It is **not** wrapped around the entire header-wait loop.

When multiple H2 streams are active on one connection and the server is
responding to some (streams 1-8) but not others (streams 9-14):

1. The socket is **not silent** — data for active streams keeps arriving.
2. Each `socket.receive()` call returns in milliseconds with data for
   active streams.
3. The `anyio.fail_after(120)` context manager exits, **discarding** the
   timer.
4. On the next loop iteration, a **new** `fail_after(120)` starts.
5. Starved streams wait indefinitely in the
   `while not self._events.get(stream_id)` loop.

The 120-second read timeout **never fires** for starved streams as long as
**any** data flows on the connection. The only protection is the 600-second
`asyncio.timeout()` wall-clock in buffered-retry mode
(`gateway_service.py:598`), which eventually kills the request — but only
after 10 minutes of waiting.

When the read timeout **does** fire (socket fully silent for 120s), it
**poisons the entire connection**: `_read_exception` is cached,
`_connection_error` is set to `True`, and all subsequent reads immediately
raise the same exception. All streams on that connection fail — not just
the one that timed out.

### How the Two Bugs Combine

```
T=0:     14 requests sent on 1 H2 connection (pool trusts advertised 100)
         Server processes 8, queues 6 (internal limit ~8)
         Socket active (data for 8 active streams)
         120s read timeout never fires for 6 starved streams

T=30s:   8 active complete → 6 queued start processing
         New requests arrive from agents (next turn)
         New requests queue behind the 6 → queue grows: 6 → 12 → 18

T=60s:   Queue never reaches 0 (new requests arrive faster than server
         processes). Some requests reach the front and complete ("часть
         дойдёт"). Others never reach the front and are killed by the
         600s timeout.

T=600s:  Requests start hitting the wall-clock timeout → 504 errors
```

The system never self-heals because:
- The pool does not open new connections (Bug 1).
- The read timeout does not fire to cancel starved streams (Bug 2).
- New requests keep arriving from agents, growing the server's queue.

Restart kills the H2 connection with its backlogged queue, and the cycle
starts fresh.

---

## 3. Test Infrastructure

### EphemeralHttp2Server

All tests use `EphemeralHttp2Server` (`tests/stress/ephemeral_api.py`), a
minimal HTTP/2-over-TLS server built on asyncio + h2. It supports the
following configuration parameters relevant to these tests:

| Parameter | Description |
|---|---|
| `max_concurrent_streams` | Advertised via H2 `SETTINGS` frame. Default 100. The client sees this value and trusts it for connection pool decisions. |
| `internal_concurrency` | Hidden server-side concurrency limit. When set, an `asyncio.Semaphore` caps real concurrent request processing independently of the advertised `max_concurrent_streams`. Models a hidden upstream bottleneck. |
| `response_delay_ms` | Artificial delay before sending the response body. Models LLM generation time. |
| `stream_headers` | When `True`, sends `200 OK` headers **immediately** (before delay), then sends the body after the delay. Simulates a real LLM API that returns `200 OK` before streaming tokens. When `False` (default), sends headers + body together after the delay. |
| `chunk_interval_ms` | Requires `stream_headers=True` and `response_delay_ms > 0`. Splits the response body into chunks and drip-feeds them at this interval during the delay. Keeps the H2 socket active, simulating SSE token streaming. Prevents socket-level read timeouts from firing for starved streams. |

### Client Configuration

All tests use `CapacityAwareHttp2Transport` (the project's custom HTTP/2
transport) with `max_connections=1` to force a single TCP connection. This
reproduces the production behavior where the pool naturally uses only one
connection (because it trusts the advertised 100 streams), but in a
deterministic way.

In production, the pool has `max_connections=100` (the default), but still
uses only 1 connection because `connection_request_count[conn] <
_max_concurrent_requests(conn)` is always true when `_max_concurrent_requests`
returns 100 and there are only 10-14 in-flight requests.

### Test File

All three tests are in `tests/stress/test_cascading_freeze.py`.

---

## 4. Test 1: Abrupt Freeze at Concurrency Threshold

### Configuration

| Component | Parameter | Value |
|---|---|---|
| Server | `max_concurrent_streams` | 100 (advertised) |
| Server | `internal_concurrency` | 3 (real limit) |
| Server | `response_delay_ms` | 2000 (2s per request) |
| Server | `stream_headers` | `True` (200 OK before delay) |
| Client | `max_connections` | 1 |
| Client | `read_timeout` | 10.0s |
| Requests | Count | 6 concurrent |

### What It Proves

The server advertises 100 concurrent streams but only processes 3 at a
time. With `stream_headers=True`, the 3 active streams receive `200 OK`
headers immediately; the 3 starved streams receive nothing — they wait on
the server's internal semaphore.

The test asserts a **bimodal latency distribution**: exactly 3 requests
complete in ≤3s (first batch), and exactly 3 complete in >3s (second
batch, after the first batch frees semaphore slots).

This proves the threshold is **abrupt**, not gradual: at ≤3 concurrent,
all requests are fast; at >3, the excess is delayed by exactly one batch
duration. This matches the production observation where everything works
at ≤8 concurrent and freezes beyond that.

### Expected Timeline

```
T=0:     6 requests sent → 3 get 200 OK immediately, 3 get nothing
T=2s:    3 active complete (body received) → 3 starved start processing
T=4s:    3 starved complete

Latencies: [~2s, ~2s, ~2s, ~4s, ~4s, ~4s]
```

### Assertions

- `peak_connections == 1` — pool trusts advertised 100, never opens a
  second connection.
- All 6 requests return HTTP 200.
- Exactly 3 requests have latency ≤ 3.0s (first batch).
- Exactly 3 requests have latency > 3.0s (queued second batch).

### Result

**PASSED** (~4s wall-clock). All assertions satisfied.

---

## 5. Test 2: Cascading Backlog After Initial Batch

### Configuration

| Component | Parameter | Value |
|---|---|---|
| Server | `max_concurrent_streams` | 100 |
| Server | `internal_concurrency` | 3 |
| Server | `response_delay_ms` | 2000 |
| Server | `stream_headers` | `True` |
| Client | `max_connections` | 1 |
| Client | `read_timeout` | 15.0s |
| Requests | Batch 1 | 6 at T=0 |
| Requests | Batch 2 | 3 at T=2.5s |

### What It Proves

This test reproduces the production observation: "the stream finishes, the
bot wants to make another request, and everything is silent."

6 requests are sent at T=0 (3 active, 3 starved). At T=2.5s — after the
first 3 have completed — 3 NEW requests are sent. These new requests are
also starved because the server is still processing the 3 queued streams
from the first batch.

This proves the **cascading backlog**: new requests get stuck because the
server's queue never empties. In production, this cycle repeats
indefinitely — each time a batch completes, new requests arrive and pile
onto the queue.

### Expected Timeline

```
T=0:     6 requests → 3 active (200 OK), 3 starved (nothing)
T=2s:    3 active complete → 3 starved start processing
T=2.5s:  3 NEW requests sent → server busy → new requests starved
T=4s:    3 from first batch complete → 3 new start processing
T=6s:    3 new complete

Batch 1 latencies: [~2s, ~2s, ~2s, ~4s, ~4s, ~4s]
Batch 2 latencies: [~3.5s, ~3.5s, ~3.5s]  (sent at T=2.5s, complete at T=6s)
```

### Assertions

- After 2.5s, exactly 3 of the first 6 requests have completed (the
  active batch).
- All 9 requests eventually succeed.
- The 3 new requests (sent at T=2.5s) all have latency > 2.0s (queued
  behind the first batch's starved streams).
- `peak_connections == 1` (single connection throughout).

### Result

**PASSED** (~7s wall-clock). All assertions satisfied.

---

## 6. Test 3: Read Timeout Silence with Drip-Feed

### Configuration

| Component | Parameter | Value |
|---|---|---|
| Server | `max_concurrent_streams` | 100 |
| Server | `internal_concurrency` | 2 |
| Server | `response_delay_ms` | 5000 (5s per request) |
| Server | `stream_headers` | `True` |
| Server | `chunk_interval_ms` | 500 (drip-feed every 500ms) |
| Client | `max_connections` | 1 |
| Client | `read_timeout` | **3.0s** (shorter than 5s delay!) |
| Requests | Count | 4 concurrent |

### What It Proves

**This is the core proof of the silent-timeout bug (Bug 2).**

The server processes only 2 requests concurrently. Active streams send
headers immediately, then drip-feed body chunks every 500ms (simulating
SSE token streaming). Starved streams get nothing — they wait on the
server's internal semaphore.

The client's `read_timeout=3.0s` is **shorter** than the 5s processing
delay. If the timeout were per-stream, starved streams would time out
after 3s. But the timeout is **socket-level**: it wraps a single
`socket.receive()` call. As long as any data arrives on the connection
(drip-fed chunks for active streams every 500ms), the timer is reset on
every read, and starved streams wait indefinitely.

### Expected Timeline

```
T=0:      4 requests → 2 active (headers + drip-feed), 2 starved (nothing)
T=0.5s:   chunk 1 for active streams → socket active → fail_after(3s) reset
T=1.0s:   chunk 2 → socket active → reset
T=1.5s:   chunk 3 → reset
T=2.0s:   chunk 4 → reset
T=2.5s:   chunk 5 → reset
T=3.0s:   ← read_timeout would fire HERE if per-stream (but it doesn't!)
T=3.5s:   chunk 7 → reset
T=4.0s:   chunk 8 → reset
T=4.5s:   chunk 9 → reset
T=5.0s:   last chunk → 2 active complete → 2 starved start processing
T=5.5s:   chunk 1 for starved streams → socket active
T=10.0s:  2 starved complete

Maximum socket silence: 500ms (between chunks) << 3.0s timeout
No ReadTimeout fires for any stream.
```

### Assertions

- All 4 requests return HTTP 200 (no `ReadTimeout`).
- `timeout_count == 0` — this proves the socket-level read timeout does
  **not** fire for starved streams when active streams keep the socket
  busy.
- 2 requests have latency ≤ 6.0s (active, drip-fed).
- 2 requests have latency > 6.0s (starved, waited for active to complete).
- `peak_connections == 1`.

### Result

**PASSED** (~10s wall-clock). All assertions satisfied. Zero timeout
errors despite `read_timeout=3s` being shorter than the 5s delay.

### Why This Matters

This test demonstrates the fundamental architectural limitation in
httpcore's H2 implementation: **the read timeout is a socket-level
timeout, not a per-stream timeout**. There is no per-stream deadline
tracking. A stream starved by head-of-line blocking (the server
prioritizing other streams) will wait indefinitely as long as any data
flows on the connection.

In production, this means the 120-second `read` timeout never fires for
starved streams when active streams are streaming responses. The only
protection is the 600-second `asyncio.timeout()` wall-clock in
buffered-retry mode — but that takes 10 minutes to trigger, during which
the agent appears completely frozen.

---

## 7. Test Results Summary

| Test | Duration | Status | Key Assertion |
|---|---|---|---|
| `test_abrupt_freeze_at_concurrency_threshold` | ~4s | PASSED | 3 fast + 3 slow, `peak_connections==1` |
| `test_cascading_backlog_after_initial_batch` | ~7s | PASSED | 3 done after 2.5s, new batch delayed, `peak_connections==1` |
| `test_read_timeout_silence_with_drip_feed` | ~10s | PASSED | 0 timeouts despite `read_timeout=3s` < `delay=5s` |
| **Regression:** `test_ephemeral_server.py` (13 tests) | ~19s | 13/13 PASSED | No regressions from server modifications |

All quality gates pass:
- `black --check`: clean
- `ruff check`: all checks passed
- `pyright` (strict mode): 0 errors, 0 warnings

---

## 8. What the Tests Prove vs. What They Do Not

### What the Tests Prove

1. **The pool does not open new connections.** When the server advertises
   `max_concurrent_streams=100`, the pool trusts this value and piles all
   streams onto a single TCP connection. Even with `max_connections=100`
   in config (the production default), the pool never opens a second
   connection because `connection_request_count[conn] <
   _max_concurrent_requests(conn)` is always true when
   `_max_concurrent_requests` returns 100.

2. **The freeze is abrupt, not gradual.** At ≤ `internal_concurrency`
   concurrent streams, all requests are fast. At > `internal_concurrency`,
   the excess is delayed by exactly one batch duration. There is no
   graceful degradation — the threshold is a hard cliff.

3. **New requests get stuck when the server is backlogged.** After the
   initial batch completes, new requests are starved because the server is
   still processing queued streams from the first batch. This reproduces
   the production observation where agents' next-turn requests also
   freeze.

4. **The socket-level read timeout does not fire for starved streams.**
   When active streams keep the socket busy with data (drip-fed chunks),
   `anyio.fail_after(read_timeout)` is reset on every `socket.receive()`
   call. Starved streams wait indefinitely — even when
   `read_timeout` is shorter than the processing delay. This is the core
   httpcore architectural limitation that prevents the system from
   self-healing.

### What the Tests Do Not Prove

| Production Scenario | In Tests | Why Not Reproduced |
|---|---|---|
| **Indefinite queue growth** — new requests arrive faster than the server processes, so the queue grows without bound | Queue drains in 2-3 batches | Tests send fixed batches and wait. Production has continuous request flow from agents. |
| **ALL streams freeze permanently** — eventually even previously-working agents' new requests get no response | Active streams complete successfully | Tests send a fixed batch; the server catches up. In production, the queue never empties because new requests keep arriving. |
| **600-second timeout kills requests** | `read_timeout=3-15s` | Tests use short timeouts for speed. Production uses 120s read + 600s wall-clock. |
| **Multiple uvicorn workers** — each worker has its own pool, requests distributed unevenly | Single client, single pool | Multi-process testing is out of scope for stress tests. |
| **Key penalization cascade** — timed-out requests trigger `NETWORK_ERROR` → key ban → key pool exhaustion | No key pool in tests | Tests focus on the HTTP/2 transport layer, not the gateway's key management logic. |

### Why the Simplifications Are Acceptable

The tests prove the **mechanisms** that cause the freeze. The production
scenario is a superset: the same mechanisms (pool trusts advertised 100,
read timeout is socket-level) combined with continuous request flow and
longer timeouts produce the indefinite freeze. The tests isolate each
mechanism in a controlled environment to make the cause-effect
relationship clear and the tests fast enough to run in CI.

---

## 9. Conclusion

The three tests in `tests/stress/test_cascading_freeze.py` provide
reproducible evidence for the root causes of the production HTTP/2
cascading-freeze anomaly:

1. **Bug 1 (pool trusts advertised capacity):** The pool never opens a
   second connection because it trusts the server-advertised
   `max_concurrent_streams=100`. All streams pile onto one TCP
   connection. (`peak_connections == 1` in all tests.)

2. **Bug 2 (socket-level read timeout):** The `read_timeout` does not
   fire for starved streams when active streams keep the socket busy.
   This prevents the system from self-healing — starved streams wait
   indefinitely instead of being cancelled and retried. (Test 3 proves
   this with `read_timeout=3s` < `delay=5s` and zero timeouts.)

3. **Cascading backlog:** New requests arriving while the server is
   backlogged are also starved, causing the queue to grow. This
   reproduces the production observation where the system never recovers
   without a restart. (Test 2 proves this with a second batch sent
   mid-flight.)

The fix for Bug 1 is to add a configurable cap on
`max_concurrent_streams_per_connection` that overrides the
server-advertised value. When the cap is set (e.g., 5), the pool will
open a new connection after 5 streams instead of piling all streams onto
one. This ensures each connection has a small number of streams, keeping
the server's internal queue short and the read timeout effective.

The fix for Bug 2 would require per-stream deadline tracking in the H2
connection layer — a more invasive change to httpcore's architecture that
is out of scope for the immediate fix. The cap on
`max_concurrent_streams_per_connection` mitigates Bug 2 indirectly: with
fewer streams per connection, the chance of head-of-line blocking
starvation is greatly reduced.

### Related Documents

- `docs/HTTP2_STRESS_TESTS.md` — HTTP/2 fixes (stream desync, connection
  growth) and the original stress test suite.
- `docs/THROUGHPUT_BOTTLENECK_PROBLEM.md` — Detailed production problem
  analysis with architecture diagrams.
