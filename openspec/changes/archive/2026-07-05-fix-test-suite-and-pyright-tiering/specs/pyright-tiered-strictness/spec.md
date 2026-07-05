## ADDED Requirements

### Requirement: Core domain logic is type-checked in strict mode
The system SHALL apply pyright's strict type-checking mode to all Python files under `src/core/` and `src/config/`. This includes the `src/core/batching/` subdirectory but excludes `src/core/http2/` (which is a temporary backport package expected to be removed).

#### Scenario: Pyright reports errors for type mismatches in src/core/
- **WHEN** a developer introduces a type error in any file under `src/core/` or `src/config/` (e.g., passing `str` where `int` is expected, missing return annotation, accessing optional without None-check)
- **THEN** `poetry run pyright` SHALL report that error with severity "error"

#### Scenario: Pyright reports unknown member access in src/core/
- **WHEN** a developer accesses a non-existent attribute or method on a typed object in `src/core/` or `src/config/`
- **THEN** `poetry run pyright` SHALL report `reportUnknownMemberType` with severity "error"

#### Scenario: Pyright reports private member access in src/core/
- **WHEN** a developer accesses a `_`-prefixed private member from outside its defining class in `src/core/` or `src/config/`
- **THEN** `poetry run pyright` SHALL report `reportPrivateUsage` with severity "error"

### Requirement: Non-core source code is type-checked in basic mode
The system SHALL apply pyright's basic type-checking mode to all Python files under `src/services/`, `src/providers/`, `src/db/`, `src/metrics/`, `src/core/http2/`, `main.py`, and the entire `tests/` directory.

#### Scenario: Basic mode still catches argument type mismatches
- **WHEN** a developer passes an argument of wrong type to a typed function in `src/services/`, `src/providers/`, `src/db/`, `src/metrics/`, or `main.py`
- **THEN** `poetry run pyright` SHALL report `reportArgumentType` with severity "error"

#### Scenario: Basic mode still catches undefined variables
- **WHEN** a developer references an undefined variable or function name in `src/services/`, `src/providers/`, `src/db/`, `src/metrics/`, or `main.py`
- **THEN** `poetry run pyright` SHALL report `reportUndefinedVariable` with severity "error"

#### Scenario: Basic mode does not report unknown member types from MagicMock
- **WHEN** test code accesses attributes on `MagicMock` or `AsyncMock` objects in `tests/`
- **THEN** `poetry run pyright` SHALL NOT report `reportUnknownMemberType` errors for those accesses

#### Scenario: Basic mode does not report untyped pytest fixture parameters
- **WHEN** test functions have untyped pytest fixture parameters (e.g., `tmp_path`, `caplog`, `monkeypatch`)
- **THEN** `poetry run pyright` SHALL NOT report `reportMissingParameterType` or `reportUnknownParameterType` errors for those parameters

#### Scenario: Basic mode does not report deliberate private member access in tests
- **WHEN** test code accesses `_`-prefixed private members of classes under test
- **THEN** `poetry run pyright` SHALL NOT report `reportPrivateUsage` errors for those accesses

### Requirement: Tiered configuration is defined in a single pyrightconfig.json
The system SHALL define the tiered strictness configuration in the root `pyrightconfig.json` file using the global `typeCheckingMode` field and the `strict` array. No nested `pyrightconfig.json` files or per-file comments SHALL be used for mode selection.

#### Scenario: Configuration format
- **WHEN** reading `pyrightconfig.json`
- **THEN** it SHALL contain `"typeCheckingMode": "basic"` at the top level
- **AND** it SHALL contain `"strict": ["src/core", "src/config"]` as a top-level field

### Requirement: CI pipeline remains operational
The system SHALL ensure that `make ci` (which runs `pyright` + `ruff` + `pytest`) completes successfully after the tiered configuration is applied and failing tests are fixed.

#### Scenario: make ci passes after implementation
- **WHEN** running `make ci`
- **THEN** `poetry run pyright` SHALL exit with code 0 (or report only warnings, not errors)
- **AND** `make test` SHALL report 885 passed, 1 xfailed, 0 failed

### Requirement: Test suite passes with all 7 previously-failing G1 tests fixed
The system SHALL ensure that `make test` (G1–G5) completes with zero failures. Specifically, the 7 tests in `tests/unit/test_main_error_handling.py` and `tests/unit/test_main_module_app.py` that previously failed SHALL now pass.

#### Scenario: test_err_01 through test_err_04 pass
- **WHEN** running `poetry run pytest tests/unit/test_main_error_handling.py -k "TestConfigErrorBlocksModuleImport"`
- **THEN** all 5 tests in `TestConfigErrorBlocksModuleImport` SHALL pass (including `test_err_01` through `test_err_05`)

#### Scenario: test_ut_m02 through test_ut_m04 pass
- **WHEN** running `poetry run pytest tests/unit/test_main_module_app.py -k "TestModuleLevelApp"`
- **THEN** all 4 tests in `TestModuleLevelApp` SHALL pass (including `test_ut_m02` through `test_ut_m04`)

### Requirement: Production code is not modified
The system SHALL implement the tiered strictness and test fixes without modifying any production source code under `src/` or `main.py`. Only configuration (`pyrightconfig.json`) and test files (`tests/unit/test_main_error_handling.py`, `tests/unit/test_main_module_app.py`) SHALL be changed.

#### Scenario: Zero production code changes
- **WHEN** reviewing the git diff for this change
- **THEN** no file under `src/` SHALL be modified
- **AND** `main.py` SHALL not be modified
