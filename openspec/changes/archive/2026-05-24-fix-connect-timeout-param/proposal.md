## Why

The `DatabasePoolConfig` Pydantic model exposes a `connect_timeout` field that is passed verbatim to `asyncpg.create_pool()`, but asyncpg's actual parameter name for TCP connection timeout is `timeout` — not `connect_timeout`. This causes a `TypeError` at startup for both Keeper and Conductor, making the entire application inoperable. Existing tests never catch this because they all mock `asyncpg.create_pool()` with `AsyncMock`, which silently accepts any keyword argument.

## What Changes

- Rename `connect_timeout` to `timeout` in `DatabasePoolConfig` (Pydantic field) — **BREAKING** for any config YAML that uses the `connect_timeout` key
- Rename `connect_timeout` to `timeout` in `init_db_pool()` function signature and the `asyncpg.create_pool()` call
- Rename `connect_timeout` to `timeout` at both call sites (keeper.py, gateway_service.py)
- Rename `connect_timeout` to `timeout` in Tier 1 defaults (`src/config/defaults.py`)
- Rename `connect_timeout` to `timeout` in example config YAML files (`example_full_config.yaml`, `example_minimal_config.yaml`)
- Update all affected tests to use the new parameter name
- Update documentation (`docs/CONFIG_SYSTEM.md`) to reflect the parameter rename

## Capabilities

### New Capabilities

<!-- No new capabilities — this is a bugfix renaming an existing parameter. -->

### Modified Capabilities

- `config-consistency`: Extend existing consistency requirement to include `DatabasePoolConfig.timeout` (renamed from `connect_timeout`) — the parameter name, default value, and constraints must be consistent across all three config tiers and match the asyncpg API.

## Impact

- **Config schema**: `DatabasePoolConfig` field rename (breaking change for YAML config files using the old key `connect_timeout`)
- **Database module**: `init_db_pool()` signature change
- **Service orchestrators**: keeper.py and gateway_service.py call sites
- **Config defaults**: Tier 1 defaults dict
- **Example configs**: `config/example_full_config.yaml`, `config/example_minimal_config.yaml`
- **Tests**: 4+ test files (unit tests for `init_db_pool`, integration tests for pool init, config schema tests)
- **Documentation**: `docs/CONFIG_SYSTEM.md`
