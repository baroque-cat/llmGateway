# http2-nonblocking-semaphore

Non-blocking semaphore extension for httpcore's `AsyncSemaphore` that adds atomic `acquire_nowait()` — the foundation for capacity-aware HTTP/2 connection routing without blocking on stream slot acquisition.

## Requirements

### Requirement: Semaphore exposes atomic acquire_nowait()

`NonBlockingSemaphore(AsyncSemaphore)` SHALL provide an `acquire_nowait()` method that atomically acquires a slot or returns `False` if no slots are available.

#### Scenario: Successful non-blocking acquire

- **WHEN** `acquire_nowait()` is called on a semaphore with at least one available slot
- **THEN** the slot is immediately acquired, the internal count decrements, and the method returns `True`

#### Scenario: Failed non-blocking acquire

- **WHEN** `acquire_nowait()` is called on a semaphore with zero available slots
- **THEN** no slot is acquired, internal count is unchanged, and the method returns `False`

#### Scenario: Asyncio backend

- **WHEN** `acquire_nowait()` is called and the backend is `"asyncio"` (anyio)
- **THEN** the method delegates to `anyio.Semaphore.acquire_nowait()` and catches `anyio.WouldBlock` to return `False`

#### Scenario: Trio backend

- **WHEN** `acquire_nowait()` is called and the backend is `"trio"`
- **THEN** the method delegates to `trio.Semaphore.acquire_nowait()` and catches `trio.WouldBlock` to return `False`

### Requirement: Semaphore is a subclass, not a monkey-patch

`NonBlockingSemaphore` SHALL inherit from `httpcore._synchronization.AsyncSemaphore` and override no existing methods other than adding `acquire_nowait()`.

#### Scenario: Backward compatible

- **WHEN** `NonBlockingSemaphore.acquire()` or `release()` is called
- **THEN** behavior is identical to `AsyncSemaphore.acquire()` and `release()` (inherited unchanged)
