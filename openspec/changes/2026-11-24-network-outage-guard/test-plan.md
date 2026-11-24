## Scope

Tests for transport classification, transport-aware retries, keeper
transport-safe writes, and the global network guard. All test configuration
values come from `tests/_canonical.py` (`CanonicalConfig`). Production URLs are
always banned by the gatekeeper, even with `# boundary:`.

## Groups

| Group | Directory | Purpose |
|---|---|---|
| G1 | `tests/unit/core/`, `tests/unit/providers/`, `tests/unit/services/` | Pure state machines, exception mapping, metrics calls |
| G2 | `tests/unit/config/` | `NetworkGuardConfig`, `on_transport_error` schema/defaults |
| G3 | `tests/integration/` | Two guard instances + shared marker, gateway 503, keeper skip |
| G5 | `tests/test_*.py` | Structural/canonical integrity |
| G6 | `tests/stress/` | Local TCP server drop/recovery, `@pytest.mark.slow` |

## P0 — transport taxonomy

- `tests/unit/providers/test_base.py` (MODIFY): parametrized mapping of
  `PoolTimeout`, `ConnectTimeout`, `ConnectError`, `ReadTimeout`
  (`"Per-stream timeout"` and normal), `WriteTimeout`,
  `RemoteProtocolError`, `LocalProtocolError`, generic `RequestError`.
  Assert `CheckResult.transport_class` and `ErrorReason`.
- `tests/unit/core/test_check_result_transport.py` (NEW): `fail`,
  `success`, `to_dict` include/omit `transport_class`.
- `tests/unit/services/test_gateway_transport_metrics.py` (NEW): memory
  metrics collector; `observe_upstream_attempt` increments attempts/outcome
  and transport failure labels; no transport metric on success.
- `tests/unit/services/test_gateway_retry_disabled.py` (NEW): debug mode or
  `retry.enabled=false` -> exactly one upstream call.

## P1 — transport retry

- Unit: transport failure does not call `_report_key_failure`; does not
  increment key/server budgets; retries the same key; invokes
  `HttpClientFactory.evict` once.
- Unit: `evict()` removes the client, creates a new one on next request, and
  closes the retired client only after the grace period (fake clock/patched
  sleep).
- Integration: fake provider returns `ConnectTimeout` then success; exactly
  two upstream calls, key status unchanged in the mocked repository.

## P3 — keeper semantics

- Unit: `update_status(transport_failure=True)` executes the metadata-only SQL
  and does not include `status`/`failing_since` in the query.
- Unit: `_update_resource_status` sets `transport_failure=True` for a
  transport class and for any failure while the guard is DOWN.
- Unit: OpenAI-like/Gemini 400 -> `BAD_REQUEST`, not `INVALID_KEY`.
- Integration: simulated outage cycle -> no key status demotion.

## P2 — network guard

- Unit: initial state UP; `mark_down`/`mark_up` transitions; `enforcing` false
  in `log` mode.
- Unit: passive window trips only with >= 3 distinct providers and >= 6
  failures in the window; stale entries are evicted.
- Unit: `startup_probe` success clears marker; failure writes marker; no
  `probe_urls` does not clear an existing marker.
- Unit: marker atomicity/TTL; expired marker ignored; fresh marker adopted by
  `poll_marker`.
- Unit: `active_loop` trips after `fail_threshold` consecutive failures and
  does not auto-recover when `auto_recover=False`.
- Integration: two `NetworkGuard` instances share a `tmp_path` marker; one
  writes, the other adopts; `mark_up` removes it.
- Integration: gateway `catch_all_endpoint` returns 503 with `Retry-After`
  when the guard is DOWN, and the provider mock is never called.
- Integration: `IResourceProbe.run_cycle` returns immediately when the guard
  is DOWN; no DB update.
- G6: local `asyncio.start_server` accepts probes; stopping it trips the
  guard; restarting it + a new guard startup probe restores UP.

## Existing tests to update

- Provider error-log tests that assert the exact `"Upstream network error"`
  string (now includes `transport=<class>`).
- Keeper tests that expect 400 -> `INVALID_KEY`.
- Config schema tests that enumerate root fields.
- `tests/_canonical.py`-based tests that assume the old field count.

## Delegation

Per `tests/AGENTS.md`, all test creation/execution is delegated to
**@Mr.Tester**. Each group is a separate request with an explicit scope and
the worktree command:

```bash
cd /home/openuser/proxy/llmGateway-netguard
/home/openuser/proxy/llmGateway/.venv/bin/python -m pytest <paths> -q --timeout=30
```

Type check:

```bash
/home/openuser/proxy/llmGateway/.venv/bin/python -m pyright \
  --pythonpath /home/openuser/proxy/llmGateway/.venv/bin/python src tests
```

## Acceptance

- All new tests pass in G1/G3; G6 passes via `make test-slow`.
- `bash scripts/check-test-hardcodes.sh all` exits 0.
- `pyright`, `ruff`, `black` clean.
- No production URL/token/model literal in tests.
