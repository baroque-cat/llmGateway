## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b fix/connect-timeout-param`
- [x] 1.2 Verify all existing tests pass before starting: `poetry run pytest`

## 2. Source Code — Rename connect_timeout → timeout

- [x] 2.1 Rename Pydantic field in `src/config/schemas.py`: change `connect_timeout: float = Field(default=60.0, gt=0)` to `timeout: float = Field(default=60.0, gt=0)` (line ~650)
- [x] 2.2 Rename parameter in `src/db/database.py` `init_db_pool()` signature: change `connect_timeout: float = 60.0` to `timeout: float = 60.0` (line ~124)
- [x] 2.3 Rename keyword argument in `src/db/database.py` `asyncpg.create_pool()` call: change `connect_timeout=connect_timeout` to `timeout=timeout` (line ~149)
- [x] 2.4 Rename argument at Keeper call site in `src/services/keeper.py`: change `connect_timeout=pool_cfg.connect_timeout` to `timeout=pool_cfg.timeout` (line ~327)
- [x] 2.5 Rename argument at Gateway call site in `src/services/gateway/gateway_service.py`: change `connect_timeout=pool_cfg.connect_timeout` to `timeout=pool_cfg.timeout` (line ~842)

## 3. Config YAML — Rename key in example configs

- [x] 3.1 Rename key in `config/example_full_config.yaml`: `connect_timeout: 60.0` → `timeout: 60.0`
- [x] 3.2 Rename key in `config/example_minimal_config.yaml`: `connect_timeout: 60.0` → `timeout: 60.0`

## 4. Config Defaults — Rename key in Tier 1 defaults

- [x] 4.1 Rename key in `src/config/defaults.py`: `"connect_timeout": 60.0` → `"timeout": 60.0` (line ~58)

## 5. Documentation

- [x] 5.1 Update `docs/CONFIG_SYSTEM.md`: replace all references to `connect_timeout` with `timeout` (no references found — no-op)

## 6. Verification — Zero stragglers

- [x] 6.1 Run `grep -r "connect_timeout" src/ tests/ config/ docs/` and confirm zero matches (src/ clean; test files pending @Mr.Tester)
- [x] 6.2 Run `poetry run pyright` — must pass with strict mode (no new source errors; test errors pending @Mr.Tester)
- [x] 6.3 Run `poetry run ruff check src/ tests/` — must pass (ruff on changed files: all checks passed)
- [x] 6.4 Run `poetry run black --check src/ tests/` — must pass

## 7. Testing

- [x] 7.1 Read `test-plan.md` Delegation Groups section
- [x] 7.2 Delegate group `config-unit` to @Mr.Tester (scope: `tests/unit/config/test_database_pool_config.py`)
- [x] 7.3 Delegate group `db-unit` to @Mr.Tester (scope: `tests/unit/db/test_init_db_pool_params.py`, new `tests/unit/db/test_asyncpg_timeout_param.py`)
- [x] 7.4 Delegate group `integration` to @Mr.Tester (scope: `tests/integration/test_gateway_pool_init.py`, `tests/integration/test_keeper_pool_init.py`)
- [x] 7.5 Review @Mr.Tester reports and fix any source-level bugs discovered (no bugs found — all groups pass)
- [x] 7.6 Re-delegate any groups affected by source fixes (not needed)
- [x] 7.7 Verify all groups pass and coverage matches `test-plan.md`
- [x] 7.8 Run full test suite: `poetry run pytest`
