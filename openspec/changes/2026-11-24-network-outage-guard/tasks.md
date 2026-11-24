## 1. Core — transport taxonomy

- [x] 1.1 Add `TransportFailureClass` to `src/core/constants.py`.
- [x] 1.2 Add `CheckResult.transport_class` and `fail(..., transport_class=...)`; include in `to_dict()`.
- [x] 1.3 Map all httpx transport exceptions in `AIBaseProvider._classify_transport_exception()`.
- [x] 1.4 Attach the class in `_send_proxy_request` and in all three adapter `check()` methods.
- [x] 1.5 Add `on_transport_error` to `RetryPolicyConfig`; defaults and validator.
- [x] 1.6 Add `NetworkGuardConfig` and root `Config.network_guard`.
- [x] 1.7 Add `ConfigAccessor.get_network_guard_config()`.

## 2. Core — network guard

- [x] 2.1 Create `src/core/network_guard.py` with UP/DOWN state, passive window, active probe, marker, startup probe, active/poll loops.
- [x] 2.2 Add process-wide `set_network_guard()` / `get_network_guard()`.
- [x] 2.3 Add guard checks to `IResourceProbe.run_cycle` and `_process_provider_batch`.

## 3. Providers

- [x] 3.1 Add transport classification/log field to `_send_proxy_request`.
- [x] 3.2 Add transport classification to OpenAI-like, Anthropic, Gemini `check()`.
- [x] 3.3 Change 400 probe mapping from `INVALID_KEY` to `BAD_REQUEST` in OpenAI-like and Gemini.

## 4. Gateway

- [x] 4.1 Add `observe_upstream_attempt()` and transport metrics.
- [x] 4.2 Add transport branch to sticky retry loop (rotate, no ban, evict).
- [x] 4.3 Add transport branch to round-robin retry loop (rotate, no ban, evict).
- [x] 4.4 Add `HttpClientFactory.evict()` with retired-client grace period.
- [x] 4.5 Zero retry budgets when `retry.enabled=false` or debug mode is active.
- [x] 4.6 Create guard in lifespan; run startup probe and marker poll loop.
- [x] 4.7 Gate `catch_all_endpoint` with 503 when guard is DOWN.
- [x] 4.8 Add `/healthz` and `/readyz`.
- [x] 4.9 Skip `_report_key_failure` for transport failures.

## 5. Keeper

- [x] 5.1 Create guard in `run_keeper`; run active probe and marker poll loops.
- [x] 5.2 Skip probe cycles when guard is DOWN.
- [x] 5.3 `update_status(transport_failure=True)` keeps status/failing_since unchanged.
- [x] 5.4 Treat any failure while guard is DOWN as transport failure.

## 6. Database

- [x] 6.1 Extend `KeyRepository.update_status` with `transport_failure`.
- [x] 6.2 Ensure no `STREAM_DISCONNECT` write to `Status` (not in enum).

## 7. Metrics / config / docs

- [x] 7.1 Add upstream/transport/stream/guard metric names and descriptions.
- [x] 7.2 Add guard and transport-retry sections to `config/example_full_config.yaml`.
- [x] 7.3 Add guard fields to `tests/_canonical.py`.
- [x] 7.4 Update this OpenSpec change (proposal/design/specs/test-plan).

## 8. Tests (delegated to @Mr.Tester)

- [ ] 8.1 P0: transport mapping, `CheckResult` serialization, metrics, retry-disabled.
- [ ] 8.2 P1: transport retry budget, no key penalty, eviction behavior.
- [ ] 8.3 P3: keeper transport write path; 400 mapping.
- [ ] 8.4 P2: guard state machine, marker TTL/atomicity, startup probe, gateway 503, keeper skip.
- [ ] 8.5 Integration: two guard instances share a marker; gateway/keeper behavior.
- [ ] 8.6 Stress (G6): local server drop/recovery; guard trip.
- [ ] 8.7 Update existing tests for the new log field and 400 mapping.

## 9. Quality gates

- [ ] 9.1 `pyright` (with `--pythonpath`) — 0 errors.
- [ ] 9.2 `ruff check src/ tests/` — 0.
- [ ] 9.3 `black --check src/ tests/` — 0.
- [ ] 9.4 `make test` (G1–G5).
- [ ] 9.5 `bash scripts/check-test-hardcodes.sh all` — 0.
- [ ] 9.6 `make test-postgres` if DB path changed.
- [ ] 9.7 Manual chaos on the VM: drop provider traffic -> guard DOWN -> restart -> UP.
