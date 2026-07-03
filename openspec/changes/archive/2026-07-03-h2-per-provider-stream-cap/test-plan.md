# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| h2-stream-cap | Per-provider max_concurrent_streams cap | Default cap of 5 applied | tests/unit/config/test_schemas.py | test_max_concurrent_streams_default_is_5 | config-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | Custom cap from YAML | tests/unit/config/test_schemas.py | test_max_concurrent_streams_custom_value | config-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | Cap lower than server-advertised value | tests/unit/core/http2/test_h2_connection.py | test_cap_lower_than_server_advertised | h2-connection-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | Cap higher than server-advertised value | tests/unit/core/http2/test_h2_connection.py | test_cap_higher_than_server_advertised | h2-connection-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | H1 providers unaffected | tests/unit/core/http2/test_h2_connection.py | test_cap_not_applied_to_h1 | h2-connection-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | Cap validates bounds | tests/unit/config/test_schemas.py | test_max_concurrent_streams_rejects_zero | config-unit |
| h2-stream-cap | Per-provider max_concurrent_streams cap | Cap passed through the transport chain | tests/unit/core/test_http_client_factory.py | test_cap_passed_from_provider_config_to_transport | factory-unit |
| h2-stream-cap | Connection labels | Connection label assigned on creation | tests/unit/core/http2/test_pool.py | test_connection_label_assigned_on_creation | pool-unit |
| h2-stream-cap | Connection labels | Multiple connections get sequential labels | tests/unit/core/http2/test_pool.py | test_multiple_connections_sequential_labels | pool-unit |
| h2-stream-cap | Connection labels | Label stored on connection | tests/unit/core/http2/test_connection.py | test_label_stored_on_connection | pool-unit |
| h2-stream-cap | Pool opens new connection when cap reached | Cap forces second connection | tests/stress/test_cap_prevents_freeze.py | test_cap_forces_second_connection | cap-stress |
| h2-stream-cap | Pool opens new connection when cap reached | All requests complete with cap | tests/stress/test_cap_prevents_freeze.py | test_all_requests_complete_with_cap | cap-stress |
| http-client-pool-config | dedicated_http_client defaults to True | Provider always gets dedicated client | tests/unit/core/test_http_client_factory.py | test_provider_always_gets_dedicated_client | factory-unit |
| http-client-pool-config | dedicated_http_client defaults to True | No shared client path | tests/unit/core/test_http_client_factory.py | test_no_shared_client_path | factory-unit |
| http-client-pool-config | Per-provider max_concurrent_streams_per_connection field | Field defaults to 5 | tests/unit/config/test_schemas.py | test_max_concurrent_streams_field_defaults_to_5 | config-unit |
| http-client-pool-config | Per-provider max_concurrent_streams_per_connection field | Field set in YAML | tests/unit/config/test_schemas.py | test_max_concurrent_streams_field_set_in_yaml | config-unit |
| http-client-pool-config | Per-provider max_concurrent_streams_per_connection field | Field validates bounds | tests/unit/config/test_schemas.py | test_max_concurrent_streams_field_rejects_zero | config-unit |
| http-client-pool-config | Per-provider max_concurrent_streams_per_connection field | Field rejects values above 1000 | tests/unit/config/test_schemas.py | test_max_concurrent_streams_field_rejects_above_1000 | config-unit |
| http2-capacity-aware-pool | Transport opens new TCP connections when H2 streams are full | Cap forces new connection before server-advertised limit | tests/unit/core/http2/test_pool.py | test_cap_forces_new_connection_before_server_limit | pool-unit |
| http2-capacity-aware-pool | Connection labels in pool | Label assigned on creation | tests/unit/core/http2/test_pool.py | test_pool_label_assigned_on_creation | pool-unit |
| http2-capacity-aware-pool | Connection labels in pool | Multiple connections sequential labels | tests/unit/core/http2/test_pool.py | test_pool_multiple_connections_sequential_labels | pool-unit |
| http2-capacity-aware-pool | Per-connection health breakdown | Per-connection details in health summary | tests/unit/core/http2/test_pool.py | test_health_summary_per_connection_details | pool-unit |
| http2-capacity-aware-pool | Per-connection health breakdown | Empty pool returns empty connections list | tests/unit/core/http2/test_pool.py | test_health_summary_empty_connections_list | pool-unit |
| http2-capacity-aware-pool | Connection creation and closure logging | Connection creation logged | tests/unit/core/http2/test_pool.py | test_connection_creation_logged | pool-unit |
| http2-capacity-aware-pool | Connection creation and closure logging | Connection closure logged | tests/unit/core/http2/test_pool.py | test_connection_closure_logged | pool-unit |
| pool-health-logging | Pool exposes health summary method | Health summary returns per-connection breakdown | tests/unit/core/http2/test_pool.py | test_health_summary_returns_per_connection_breakdown | pool-unit |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health log line format with per-connection details | tests/unit/services/test_gateway_core.py | test_health_log_includes_per_connection_details | gateway-unit |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging respects configured interval | tests/unit/services/test_gateway_core.py | test_health_logging_respects_interval | gateway-unit |
| pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging disabled when interval is zero | tests/unit/services/test_gateway_core.py | test_health_logging_disabled_when_zero | gateway-unit |

## Delegation Groups

### Group: config-unit

**Scope:** tests/unit/config/

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/config/test_schemas.py | 6 | MODIFY |
| tests/unit/config/test_validator.py | 5 | MODIFY |
| tests/unit/config/test_defaults.py | 2 | MODIFY |
| tests/integration/test_config_examples.py | 2 | MODIFY |

### Group: factory-unit

**Scope:** tests/unit/core/test_http_client_factory.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/core/test_http_client_factory.py | 4 | MODIFY |

### Group: h2-connection-unit

**Scope:** tests/unit/core/http2/test_h2_connection.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/core/http2/test_h2_connection.py | 4 | NEW |

### Group: pool-unit

**Scope:** tests/unit/core/http2/test_pool.py, tests/unit/core/http2/test_connection.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/core/http2/test_pool.py | 10 | NEW |
| tests/unit/core/http2/test_connection.py | 1 | NEW |

### Group: gateway-unit

**Scope:** tests/unit/services/test_gateway_core.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/unit/services/test_gateway_core.py | 3 | MODIFY |

### Group: cap-stress

**Scope:** tests/stress/test_cap_prevents_freeze.py

| Test File | Scenarios | Action |
|---|---|---|
| tests/stress/test_cap_prevents_freeze.py | 2 | NEW |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| tests/unit/config/test_schemas.py | Add tests for `max_concurrent_streams_per_connection` field (default, custom, bounds) | New requirement: Per-provider max_concurrent_streams_per_connection field |
| tests/unit/config/test_validator.py | Remove G2-1.1 through G2-1.5 tests for `dedicated_http_client`; add validation tests for new field | REMOVED requirement: dedicated_http_client defaults to True |
| tests/unit/config/test_defaults.py | Remove `test_default_config_dedicated_http_client`; add test for new field in defaults | REMOVED requirement: dedicated_http_client defaults to True |
| tests/integration/test_config_examples.py | Remove IT-Y07-2 assertions for `dedicated_http_client`; add assertions for new field | REMOVED requirement: dedicated_http_client defaults to True |
| tests/unit/core/test_http_client_factory.py | Remove Section 2 (cache-key tests for shared path), Section H (shared client pooling), SEC-1/SEC-2 (collision tests); simplify cache-key tests to always return provider_name; add test for cap passed from ProviderConfig to transport | REMOVED requirement: dedicated_http_client; NEW requirement: cap passed through transport chain |
| tests/unit/services/test_gateway_core.py | Update health log assertions for per-connection breakdown format | MODIFIED requirement: Health log line format with per-connection details |
| tests/stress/test_ephemeral_server.py | No changes needed (stream_headers/chunk_interval_ms already added in prior change) | N/A |
| tests/stress/test_throughput_bottleneck.py | No changes needed (existing tests still valid) | N/A |
| tests/stress/test_cascading_freeze.py | No changes needed (existing tests prove the problem) | N/A |

## Risks & Edge Cases

- **Default=5 may be too low for high-throughput providers** → test_cap_forces_second_connection (stress) verifies that the pool opens additional connections without errors when cap=5 and 6 requests are sent
- **Breaking config change (dedicated_http_client removal)** → test_provider_always_gets_dedicated_client and test_no_shared_client_path verify the simplified cache-key logic; config tests verify `extra="forbid"` rejects stale YAML
- **More TCP connections opened** → test_all_requests_complete_with_cap (stress) verifies all requests succeed with cap=5 against a server with internal_concurrency=8, confirming no cascading freeze
- **Connection label ordinal is per-pool** → test_multiple_connections_sequential_labels verifies ordinals are sequential within a pool; no cross-pool collision test needed since each provider has its own pool
