# HTTP/2 Connection Pool Throughput Bottleneck: Production Problem Analysis

## Summary

The llmGateway becomes **non-functional at ~8 concurrent streams per provider**, despite the connection pool reporting `max_capacity: 100`. All active streams freeze simultaneously; some requests complete after **minutes** of waiting, others hit the **600-second gateway timeout**. This triggers a cascading key-penalization loop that burns through the entire API key pool — a failure indistinguishable from a provider outage, but caused entirely by our own infrastructure.

---

## How the problem manifests

### Production log signature

```
HTTP_POOL_HEALTH | provider=qwen-home | conns: 1 total (1 active, 0 idle) |
  proto: 1 H2 / 0 H1 | streams: 14 active / 100 max_capacity | queued: 0
```

Key observations:

- **1 connection, 14 active streams** — all requests funnel through a single TCP connection.
- **max_capacity = 100** — the pool believes the connection can handle 100 concurrent streams, so 14 out of 100 looks like 86% headroom. The pool has no reason to open more connections.
- **queued = 0** — no requests are waiting for a connection slot at the httpx level. All 14 are "in flight" on the single H2 connection.
- **conns = 1** — despite `max_connections = 100` in config, only one TCP connection is ever opened for this provider.

### User-visible symptoms

1. **All streams freeze simultaneously.** At ~8 concurrent streams, latency spikes from sub-second to **minutes** for ALL requests on that connection — not just the ones beyond some internal limit.

2. **Bimodal completion pattern.** Some requests eventually complete (after 60-300 seconds), while others hit the 600-second gateway timeout and fail.

3. **Cascading key penalization.** Each timeout is classified as `ErrorReason.NETWORK_ERROR`, which triggers retry. Each retry opens a NEW stream on the SAME connection — compounding the problem. After 3 retries, the key is penalized:
   ```
   key → penalized → removed from pool → next key → same connection → same failure
   ```
   The Gateway rotates through **~50 keys**, all penalized, before the service is restarted. None of the keys are actually bad.

4. **Restart temporarily fixes it.** After a service restart, all connections are closed. New connections are created fresh, and the cycle repeats when concurrency climbs again.

---

## When it happens

The failure triggers at concurrency levels **far below** the advertised `SETTINGS_MAX_CONCURRENT_STREAMS`:

| Reported capacity | Failure threshold | Ratio |
|---|---|---|
| `max_capacity: 100` | ~8 concurrent streams | 8% |

This is consistent across providers. The exact threshold varies (6-12 streams) but is always **an order of magnitude below** the visible capacity.

Typical trigger scenario:

```
1. Normal operation: 0-5 concurrent requests → sub-second latency
2. Load increase: 6-8 concurrent requests → latency begins to rise
3. Threshold crossed: 9+ concurrent requests → ALL streams freeze
4. Time passes: some complete (minutes), some timeout (600s)
5. Keys burn: cascading penalization
6. Restart required
```

---

## Root cause: the client-visible capacity is a lie

### Where `max_capacity = 100` comes from

The value `100` is NOT negotiated with the LLM API. It comes from our **own local h2 configuration**:

```
h2.config.H2Configuration()
  └─ max_concurrent_streams = 100  (library default, never changed)

httpcore HTTP/2 connection init:
  └─ self._h2_state.local_settings.MAX_CONCURRENT_STREAMS = 100

FixedHTTP2Connection.max_concurrent_requests():
  └─ return self._max_streams
     = min(server_SETTINGS_value, local_settings_max_streams)
     = min(what_we_receive, 100)
```

The value we receive in the SETTINGS frame depends on what our client talks to:

```
With HTTP forward proxy (httpx proxy=):
┌──────────┐     H2 handshake     ┌─────────┐     ???      ┌──────────┐
│ GATEWAY  │ ◄──────────────────► │  PROXY  │ ◄──────────► │ LLM API  │
│  (we)    │   SETTINGS from      │         │  hidden      │ (Qwen)   │
│          │   PROXY, not LLM!    │         │  bottleneck  │          │
└──────────┘                      └─────────┘              └──────────┘
     ↑                                ↑                        ↑
     └── we see THIS value ───────────┘                        │
        (could be proxy's own limit,               Real limit: invisible
         could be 100, could be anything)           to our client
```

Without proxy (direct connection):

```
┌──────────┐     H2 handshake     ┌──────────┐
│ GATEWAY  │ ◄──────────────────► │ LLM API  │
│  (we)    │   SETTINGS from      │ (Qwen)   │
│          │   LLM server         │          │
└──────────┘                      └──────────┘
     ↑                                ↑
     └── we see LLM's SETTINGS ───────┘
        (may still lie: advertise 100, process 8)
```

In **both** cases, our client trusts whatever SETTINGS value it receives. We have **no way to know** the real upstream throughput capacity.

### What actually happens at the upstream

The upstream (proxy, LLM server, or the combination) has an internal concurrency limit far lower than the H2-level SETTINGS value. When streams exceed this hidden limit:

1. The upstream **accepts** all H2 streams (SETTINGS says 100, and it won't violate its own H2-level promise by sending RST_STREAM).
2. The upstream **silently queues** the excess requests internally (web server worker pool, load balancer queue, API rate limiter).
3. Requests in the queue **hold their H2 stream open** — from the client's perspective, the stream is "active" and waiting for a response.
4. Since the stream is open and the read timeout is per-chunk (120s), the client sees no error and waits.

### Why ALL streams freeze, not just the excess

This is the critical detail. The upstream's internal queue is **not independent per-stream** — it is a **shared resource**. When the queue is full or the upstream is overloaded, ALL streams experience the same slow path:

```
Upstream state at 14 concurrent streams on one connection:
┌─────────────────────────────────────────────────────────┐
│  Active processing slots:  8 (internal worker limit)     │
│  Internal queue:           6 requests                    │
│                                                         │
│  ALL 14 streams share:                                  │
│    - The same TCP connection (single H2 session)        │
│    - The same upstream server process                   │
│    - The same internal request queue                    │
│                                                         │
│  Result: when queue pressure is high, ALL streams       │
│          experience elevated latency, not just the      │
│          ones in the queue. The entire connection       │
│          becomes a bottleneck.                          │
└─────────────────────────────────────────────────────────┘
```

The 8 "active" processing slots may also be slow because the upstream server is under load from the queued requests — context switching, memory pressure, or rate-limiting mechanisms that apply at the connection level rather than the stream level.

---

## Why the pool never opens more connections

The capacity-aware pool in `src/core/http2/pool.py` decides whether to open new connections based on `max_concurrent_requests()`:

```python
# pool.py:155-165 — capacity check for assigning requests
available_connection = next(
    (
        conn
        for conn in self._connections
        if conn.can_handle_request(origin)
        and conn.is_available()
        and connection_request_count[conn] < self._max_concurrent_requests(conn)
    ),
    None,
)

# If no available connection found:
elif len(self._connections) < self._max_connections:
    connection = self.create_connection(origin)  # opens new connection
```

The decision chain:

```
connection_request_count[conn] = 14
_max_concurrent_requests(conn) = max_concurrent_requests() = 100
14 < 100 → TRUE → "this connection has capacity" → DO NOT open new connection
```

The pool logic is **correct** for what it knows. The bug is not in the routing — it's in the **capacity estimate**. `max_concurrent_requests()` returns the client-visible SETTINGS value, which is 10× higher than reality.

---

## Why the existing stress tests miss this

The stress test suite (`tests/stress/`) tests two scenarios
that are now augmented by additional tests:

1. **Connection growth** (`test_connection_growth.py`) — proves the pool opens new connections when H2 streams ARE exhausted at the semaphore level. The server's `max_concurrent_streams` matches its real capacity.

2. **Pool saturation** (`test_pool_saturation.py`) — proves `PoolTimeout` is raised when all connections are at stream capacity.

3. **Cascading freeze** (`test_cascading_freeze.py`) — added to reproduce the exact production scenario: server advertises 100 but processes 3—8 internally. Three tests prove abrupt freeze at threshold, cascading backlog, and read-timeout silence with drip-feed.

4. **Cap-based fix** (`test_cap_prevents_freeze.py`) — added to validate the deployed `max_concurrent_streams_per_connection` cap (default 5). Two tests prove the cap forces multiple connections and prevents the cascading freeze.

5. **Throughput bottleneck diagnostics** (`test_throughput_bottleneck.py`) — added to diagnose the hidden upstream bottleneck. See [below](#what-the-diagnostic-tests-prove).

---

## Impact summary

| Aspect | Detail |
|---|---|
| **Failure mode** | All streams on a connection freeze simultaneously at ~8 concurrent requests |
| **Visible capacity** | `max_capacity: 100` without cap → pool trusts advertised 100. With `max_concurrent_streams_per_connection=5`: `max_capacity: 5` in `HTTP_POOL_HEALTH` logs. |
| **Real capacity** | Estimated 8-10 (hidden upstream bottleneck) |
| **Pool behavior** | Without cap: trusts `max_concurrent_requests() = 100` — no reason to open more connections. With cap: opens new connection after 5 streams, distributing load. |
| **Gateway behavior** | No wall-clock timeout in default streaming mode; per-chunk read timeout = 120s |
| **Cascade** | Timeouts → key retries → new streams on same connection → more timeouts → key penalization → rotation through all keys |
| **Mitigation** | `max_concurrent_streams_per_connection` cap (default 5) limits streams per connection, forcing pool to open new connections before hidden limit is reached. Service restart is a fallback. |
| **Detectability** | Not visible in standard metrics; `max_capacity: 100` looks healthy. With the cap (default 5), `max_capacity: 5` is visible in `HTTP_POOL_HEALTH` logs. |

---

## What the diagnostic tests prove

The tests in `tests/stress/test_throughput_bottleneck.py` model the exact
production scenario with `internal_concurrency` (a hidden server-side
limit) lower than `max_concurrent_streams` (the advertised SETTINGS value):

- **Test A** (`test_single_connection_bottleneck`) proves the bottleneck:
  `internal_concurrency=8`, `max_concurrent_streams=100`, 20 requests on
  1 transport → `peak_connections == 1`, bimodal latency (≥8 fast, ≥5
  slow), all succeed but take 3× longer for queued requests.

- **Test B** (`test_multi_connection_mitigation`) proves that distributing
  requests across **3 transports** (3 connections) does **not** fully
  mitigate the problem — `internal_concurrency` is a server-side/shared
  limit.  Latency is bounded but not uniform (3 batches:
  8@~5s, 8@~10s, 5@~15s).  All 21 requests still succeed.

- **Test C** (`test_production_timeout_cascade`) is **skipped**
  (`pytest.skip`): it attempted to reproduce the 600-second timeout
  cascade (`internal_concurrency=3`, 120s timeout) but had unreliable
  timing dependencies and needs to be rewritten.
