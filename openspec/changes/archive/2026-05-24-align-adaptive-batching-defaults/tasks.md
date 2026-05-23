## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b fix/align-adaptive-batching-defaults`
- [x] 1.2 Run the full test suite to establish a passing baseline before making changes: `poetry run pytest`

## 2. Source Changes

- [x] 2.1 In `src/config/schemas.py` line 132, change `Field(default=30, gt=0)` to `Field(default=10, gt=0)` for `start_batch_size`
- [x] 2.2 In `src/config/schemas.py` line 133, change `Field(default=15.0, ge=0)` to `Field(default=30.0, ge=0)` for `start_batch_delay_sec`
- [x] 2.3 Verify the change compiles and type-checks: `poetry run pyright`

## 3. Testing

- [x] 3.1 Read `test-plan.md` Delegation Groups section
- [x] 3.2 Delegate group `config-unit` to @Mr.Tester (scope: tests/unit/config/ — update `test_validator.py`, `test_adaptive_batching_config_to_params.py`)
- [x] 3.3 Delegate group `core-unit` to @Mr.Tester (scope: tests/unit/core/ — update `test_probes_dispatcher.py`)
- [x] 3.4 Delegate group `batching-unit` to @Mr.Tester (scope: tests/test_batching/ — update `test_adaptive_batching_config.py`, `test_adaptive_controller.py`, `test_adaptive_security.py`, `test_probe_adaptive_integration.py`)
- [x] 3.5 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 3.6 Re-delegate any groups affected by source fixes
- [x] 3.7 Verify all groups pass and coverage matches `test-plan.md`

## 4. Quality Gates

- [x] 4.1 Run `poetry run pyright` — must pass with zero errors
- [x] 4.2 Run `poetry run ruff check src/ tests/` — must pass with zero errors
- [x] 4.3 Run `poetry run black --check src/ tests/` — must report no changes needed
- [x] 4.4 Run `poetry run pytest` — must pass all tests
