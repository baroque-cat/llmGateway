## Context

Commit `41f2711` ("fix: network hangs prevention and observability improvements") added `command_timeout` and `connect_timeout` parameters to `DatabasePoolConfig`. While `command_timeout` is a valid asyncpg parameter (passed through `create_pool()` → `connect()`'s `**connect_kwargs`), `connect_timeout` is NOT recognized by `asyncpg.connect()`. The correct parameter name is `timeout`.

The incorrect parameter name causes a `TypeError` at pool initialization time — crashing both Keeper and Conductor on startup. The bug exists in 8 locations across the codebase: the Pydantic schema, Tier 1 defaults, `init_db_pool()` function, two call sites, two example config YAMLs, and documentation.

Existing tests verify that the parameter is forwarded correctly — but only to a mocked `AsyncMock`, which silently accepts any keyword argument. No test calls the real `asyncpg.create_pool()`, so the API mismatch is invisible to the test suite.

## Goals / Non-Goals

**Goals:**
- Rename `connect_timeout` → `timeout` in `DatabasePoolConfig` Pydantic field to match asyncpg's actual API
- Propagate the rename through all layers: Pydantic schema → defaults → function signatures → call sites → config YAMLs → docs
- Update all affected tests so they verify the correct parameter name
- Ensure the application starts successfully with real asyncpg after the fix

**Non-Goals:**
- Adding new pool configuration parameters
- Changing the `command_timeout` parameter (it is correct as-is)
- Adding integration tests with a real PostgreSQL instance (out of scope for this fix)
- Changing the default timeout value (stays at 60.0)
- Adding a backward-compatibility alias (`connect_timeout`) in the config schema — the old key was introduced in the same unreleased branch and has no production users

## Decisions

### Decision 1: Direct rename everywhere (no mapping layer)

**Alternative considered**: Add a mapping layer in `init_db_pool()` that translates `connect_timeout` → `timeout` at the asyncpg boundary while keeping `connect_timeout` in the Pydantic model.

**Why rejected**: A mapping layer introduces naming divergence between "what the config calls it" and "what asyncpg calls it". This is confusing and fragile — future developers would need to remember that `connect_timeout` in config maps to `timeout` in asyncpg. A direct rename aligns the codebase with the library API, making the code self-documenting.

**Why acceptable**: The `connect_timeout` key was introduced in commit `41f2711` on the `unstable` branch — it has never been in a stable release. There are zero production users who could be broken by the rename.

### Decision 2: Rename in all files in a single atomic commit

All 8 files must be changed together because the parameter name is part of the function signature in `init_db_pool()`. Changing the function signature without updating call sites would cause `TypeError`; changing call sites without changing the function would also fail. A single atomic commit ensures consistency.

### Decision 3: Keep the Pydantic field constraints unchanged

The `Field(gt=0)` constraint and default value of `60.0` remain identical — only the field name changes. No validation logic is affected.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Someone has a YAML config with the old `connect_timeout` key | The key was added in the same unreleased `unstable` branch — no released version contains it. The config schema uses Pydantic v2 which silently ignores unknown fields by default, so an old key would be harmless (just unused). |
| Missed a reference to the old name during rename | A `grep -r "connect_timeout" src/ tests/ config/ docs/` after the rename will catch any stragglers. Added as explicit verification step in tasks. |
| Tests still don't validate real asyncpg API | Out of scope for this fix. A follow-up task to add a real-asyncpg smoke test is recorded as a Future Work note. |

## Future Work

- Add a smoke test that initializes a real `asyncpg.create_pool()` (e.g., against a Dockerized test PostgreSQL) to catch API mismatches at CI time rather than at runtime.
- Consider adding a `pyproject.toml` check or custom lint rule that cross-references keyword arguments passed to `create_pool()` against the asyncpg signature.
