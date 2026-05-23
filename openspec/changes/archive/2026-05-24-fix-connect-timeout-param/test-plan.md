# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | config-consistency | DatabasePoolConfig timeout field is consistent across config tiers | Pydantic default matches defaults.py | `tests/unit/config/test_database_pool_config.py` | `test_timeout_default` | config-unit |
| 2 | config-consistency | DatabasePoolConfig timeout field is consistent across config tiers | Pydantic default matches example_full_config.yaml | `tests/unit/config/test_database_pool_config.py` | `test_yaml_with_default_timeouts` | config-unit |
| 3 | config-consistency | DatabasePoolConfig timeout field is consistent across config tiers | Custom timeout value propagates correctly | `tests/unit/config/test_database_pool_config.py` | `test_yaml_with_custom_timeout_value` | config-unit |
| 4 | config-consistency | DatabasePoolConfig timeout field name matches asyncpg API | init_db_pool forwards timeout to asyncpg.create_pool | `tests/unit/db/test_init_db_pool_params.py` | `test_init_db_pool_forwards_timeout_param` | db-unit |
| 5 | config-consistency | DatabasePoolConfig timeout field name matches asyncpg API | Timeout parameter reaches asyncpg.connect via create_pool | `tests/unit/db/test_asyncpg_timeout_param.py` | `test_asyncpg_connect_accepts_timeout_kwarg` | db-unit |
| 6 | config-consistency | DatabasePoolConfig timeout field validates positive values | Zero timeout value is rejected | `tests/unit/config/test_database_pool_config.py` | `test_timeout_zero_rejected` | config-unit |
| 7 | config-consistency | DatabasePoolConfig timeout field validates positive values | Negative timeout value is rejected | `tests/unit/config/test_database_pool_config.py` | `test_timeout_negative_rejected` | config-unit |
| 8 | config-consistency | DatabasePoolConfig timeout field validates positive values | Positive timeout value is accepted | `tests/unit/config/test_database_pool_config.py` | `test_timeout_positive_accepted` | config-unit |

## Delegation Groups

### Group: `config-unit`

**Scope:** `tests/unit/config/test_database_pool_config.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_database_pool_config.py` | 5 | MODIFY (rename fields + assertions) + NEW tests |

**Description:** Validates `DatabasePoolConfig` Pydantic schema: defaults, YAML loading, positive-value validation, zero/negative rejection — all with renamed `connect_timeout` → `timeout`.

---

### Group: `db-unit`

**Scope:** `tests/unit/db/test_init_db_pool_params.py`, `tests/unit/db/test_asyncpg_timeout_param.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/db/test_init_db_pool_params.py` | 1 | MODIFY (rename assertions) + add new scenario test |
| `tests/unit/db/test_asyncpg_timeout_param.py` | 1 | NEW (verify real asyncpg API signature) |

**Description:** Verifies that `init_db_pool` forwards `timeout` (not `connect_timeout`) to `asyncpg.create_pool`, and that the real asyncpg library actually accepts the `timeout` keyword argument (via `inspect.signature` — no live PostgreSQL needed).

---

### Group: `integration`

**Scope:** `tests/integration/test_gateway_pool_init.py`, `tests/integration/test_keeper_pool_init.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/integration/test_gateway_pool_init.py` | 0 | MODIFY (rename `connect_timeout` → `timeout` in assertion) |
| `tests/integration/test_keeper_pool_init.py` | 0 | MODIFY (rename `connect_timeout` → `timeout` in assertion) |

**Description:** Updates integration test assertions for gateway and keeper lifespan to expect `timeout` instead of `connect_timeout` in pool-init calls. No new scenarios — purely mechanical renames.

---

## Test Modifications

### File: `tests/unit/config/test_database_pool_config.py`

| Change | Reason |
|---|---|
| Rename `test_connect_timeout_default` → `test_timeout_default`; change assertion from `pool.connect_timeout` to `pool.timeout` | Matches Scenario 1: Pydantic default must equal 60.0 under correct field name |
| Rename `test_connect_timeout_zero_rejected` → `test_timeout_zero_rejected`; change `connect_timeout=0` to `timeout=0`, update error assertion to reference `timeout` | Matches Scenario 6: zero value must be rejected under correct field name |
| In `test_yaml_with_custom_timeouts`, change YAML key `connect_timeout: 90.0` → `timeout: 90.0`, assertion `connect_timeout` → `timeout` | Existing custom-timeout test must use the new field name; supports Scenarios 2/3 |
| Add new test `test_timeout_negative_rejected`: `DatabasePoolConfig(timeout=-1)` → `ValidationError` | Matches Scenario 7: negative value rejection |
| Add new test `test_timeout_positive_accepted`: `DatabasePoolConfig(timeout=30.0)` → no error | Matches Scenario 8: positive value accepted |
| Add new test `test_yaml_with_default_timeouts`: YAML with `timeout: 60.0` + `command_timeout: 30.0` loads correctly | Matches Scenario 2: YAML with default values matches Pydantic defaults |

### File: `tests/unit/db/test_init_db_pool_params.py`

| Change | Reason |
|---|---|
| In `test_init_db_pool_default_params`: assertion `connect_timeout=60.0` → `timeout=60.0` | Rename in assert_called_once_with to match new function signature |
| In `test_init_db_pool_custom_params`: assertion `connect_timeout=60.0` → `timeout=60.0` | Rename in assert_called_once_with to match new function signature |
| In `test_init_db_pool_custom_timeouts`: call arg `connect_timeout=10.0` → `timeout=10.0`; assertion `connect_timeout=10.0` → `timeout=10.0`; rename function to `test_init_db_pool_forwards_timeout_param` | Matches Scenario 4: custom timeout forwarded as `timeout=` keyword to asyncpg |
| In `test_init_db_pool_second_call_logs_warning`: assertion `connect_timeout=60.0` → `timeout=60.0` | Rename in assert_called_once_with to match new function signature |

### File: `tests/integration/test_gateway_pool_init.py`

| Change | Reason |
|---|---|
| In `test_gateway_pool_init_custom_params`: assertion `connect_timeout=60.0` → `timeout=60.0` | Rename in assert_called_once_with to match new init_db_pool signature used by gateway lifespan |

### File: `tests/integration/test_keeper_pool_init.py`

| Change | Reason |
|---|---|
| In `test_keeper_pool_init_default_params`: assertion `connect_timeout=60.0` → `timeout=60.0` | Rename in assert_called_once_with to match new init_db_pool signature used by keeper startup |

---

## Risks & Edge Cases

### Risk: Old `connect_timeout` key in user YAML config
- **Mitigation:** Pydantic v2 ignores unknown fields by default on `DatabasePoolConfig` (no `extra="forbid"`). An old `connect_timeout` key is silently dropped — no crash.
- **Edge Case:** YAML contains both old `connect_timeout` key and new `timeout` key — new key should take effect, old key silently ignored. No dedicated test for this; verified by the existing `SEC-06` test (`test_sec_06_unknown_field_in_pool_silently_ignored`) which confirms unknown fields are silently dropped.

### Risk: Missed `connect_timeout` reference after rename
- **Mitigation:** A `grep -r "connect_timeout" src/ tests/ config/ docs/` sweep after the rename catches any stragglers. This is a manual verification step, not an automated test.
- **Edge Case:** None — grep is exhaustive.

### Risk: asyncpg API mismatch — `timeout` keyword not recognized by real asyncpg
- **Mitigation:** New test `test_asyncpg_connect_accepts_timeout_kwarg` in `tests/unit/db/test_asyncpg_timeout_param.py` uses `inspect.signature(asyncpg.connect)` to verify `timeout` is a valid parameter. No real PostgreSQL connection required — catches the original bug class (wrong keyword argument name) at CI time.
- **Edge Case:** If `asyncpg` is not installed in the test environment, the test will fail to import. This is acceptable — `asyncpg` is a core production dependency listed in `pyproject.toml`.

### Edge Case: `command_timeout` field untouched
- The rename must not affect `command_timeout`. Existing tests for `command_timeout` defaults and validation (`test_command_timeout_default`, `test_command_timeout_zero_rejected`) remain unchanged and must continue to pass. No modification needed.

### Edge Case: Pydantic `Field(gt=0)` constraint with floating-point precision
- Extremely small positive values (e.g., `timeout=1e-10`) are accepted by `gt=0`. This is intentional — the constraint only rejects zero and negative values. Covered implicitly by Scenario 8 (positive accepted).

### Edge Case: `command_timeout` vs `timeout` in `create_pool` call
- `command_timeout` is a valid asyncpg `create_pool()` parameter (controls per-query timeout). `timeout` maps to `connect()` via `**connect_kwargs`. Both are forwarded correctly. The modified tests under `db-unit` verify the full `create_pool` call signature includes both parameters with correct names.
