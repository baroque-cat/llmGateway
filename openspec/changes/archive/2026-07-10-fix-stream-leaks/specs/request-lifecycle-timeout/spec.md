## ADDED Requirements

### Requirement: Timeout handler closes upstream response
When `asyncio.TimeoutError` is caught in `_handle_buffered_retryable_request()`,
the handler SHALL guarantee that the current `upstream_response` is closed via
`discard_response()` before returning the 504 JSONResponse. The closure SHALL
be implemented via a `finally` block wrapping the entire `async with asyncio.timeout()`
scope.

#### Scenario: Timeout fires with open upstream response
- **WHEN** `asyncio.timeout` fires while an upstream response is open
  (body_bytes is None, stream not yet forwarded or discarded)
- **THEN** `discard_response(upstream_response, body_bytes)` SHALL be called
  in the `finally` block
- **AND** `upstream_response.aclose()` SHALL be invoked
- **AND** the 504 JSONResponse SHALL be returned to the client

#### Scenario: Timeout fires after response already closed
- **WHEN** `asyncio.timeout` fires during `asyncio.sleep()` backoff after
  `discard_response()` has already been called on the current attempt
  (upstream_response is not None, body_bytes is not None, response already discarded)
- **THEN** `discard_response()` in `finally` SHALL be a safe no-op
  (body_bytes is not None, so discard_response returns without calling aclose())

#### Scenario: Timeout fires before any proxy_request call
- **WHEN** `asyncio.timeout` fires before the first `provider.proxy_request()` call
  (e.g., during initial `get_key_from_pool()` delay)
- **THEN** `upstream_response` SHALL be `None`
- **AND** the `finally` block SHALL skip `discard_response()` entirely

#### Scenario: discard_response failure is logged, not raised
- **WHEN** `discard_response()` in the `finally` block raises an exception
- **THEN** the exception SHALL be logged at ERROR level with `exc_info=True`
- **AND** the original `TimeoutError` SHALL NOT be masked
- **AND** the 504 JSONResponse SHALL still be returned
