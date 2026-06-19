## ADDED Requirements

### Requirement: Connection cleans up h2 stream state after asyncio cancellation

`FixedHTTP2Connection._response_closed()` SHALL synchronize the h2 library's stream state with httpcore's semaphore after asyncio task cancellation.

#### Scenario: Normal stream close (no cancellation)

- **WHEN** `_response_closed(stream_id)` is called and the stream was cleanly closed by the server (stream_id is in `_closed_streams`)
- **THEN** no `reset_stream()` is called, the semaphore is released (if capacity allows), and `_closed_streams` entry is discarded

#### Scenario: Cancelled stream (stream not in _closed_streams)

- **WHEN** `_response_closed(stream_id)` is called and `stream_id` is NOT in `_closed_streams` (stream was cancelled before server response)
- **THEN** `h2_state.reset_stream(stream_id)` is called, errors (`NoSuchStreamError`, `StreamClosedError`, `ProtocolError`) are silently caught, and the semaphore is released conditionally

#### Scenario: Semaphore release is conditional

- **WHEN** `_response_closed(stream_id)` releases the semaphore
- **THEN** the release only occurs if `len(self._events) <= self._max_streams` to prevent semaphore overflow

#### Scenario: Connection closes when stream was reset

- **WHEN** `_response_closed` completes for a `stream_was_reset` stream and no more events are active
- **THEN** the connection is closed via `aclose()` instead of transitioning to IDLE, preventing inconsistent state

### Requirement: Connection tracks server-closed streams

`FixedHTTP2Connection` SHALL maintain a `_closed_streams: set[int]` to track streams that the server cleanly closed (via `StreamEnded` or `StreamReset` events).

#### Scenario: Server closes stream cleanly

- **WHEN** `_receive_events()` processes a `h2.events.StreamEnded` or `h2.events.StreamReset` event for an active stream
- **THEN** the event's `stream_id` is added to `self._closed_streams`

### Requirement: Connection advertises H2 stream capacity

`FixedHTTP2Connection.is_available()` SHALL return `False` when all H2 streams are occupied, in addition to existing checks (CLOSED state, connection errors, exhausted stream IDs).

#### Scenario: Connection is full

- **WHEN** `is_available()` is called and `len(self._events) >= self.max_concurrent_requests()`
- **THEN** the method returns `False`, preventing the pool from assigning new requests

#### Scenario: Connection has room

- **WHEN** `is_available()` is called and `len(self._events) < self.max_concurrent_requests()` and all other checks pass
- **THEN** the method returns `True`

### Requirement: Connection signals pool on SETTINGS change

`FixedHTTP2Connection._receive_remote_settings_change()` SHALL call `self._on_capacity_update()` callback after adjusting the semaphore when the server changes `SETTINGS_MAX_CONCURRENT_STREAMS`.

#### Scenario: Server increases stream limit

- **WHEN** `_receive_remote_settings_change()` processes a new `SETTINGS_MAX_CONCURRENT_STREAMS` value higher than current
- **THEN** the semaphore is released for the new slots, `_max_streams` is updated, and `_on_capacity_update()` is called if set

#### Scenario: No callback configured

- **WHEN** `_on_capacity_update` is `None`
- **THEN** no callback is called, semaphore adjustment proceeds normally

### Requirement: Connection returns max concurrent requests

`FixedHTTP2Connection.max_concurrent_requests()` SHALL return the number of streams this connection can handle concurrently.

#### Scenario: Connection initialized

- **WHEN** `max_concurrent_requests()` is called after `_sent_connection_init` is `True`
- **THEN** the method returns `self._max_streams`

#### Scenario: Connection not yet initialized

- **WHEN** `max_concurrent_requests()` is called before `_sent_connection_init` is `True`
- **THEN** the method returns `1`
