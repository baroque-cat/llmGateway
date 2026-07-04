## Why

After Phase 3 established CanonicalConfig, the gatekeeper script, cache fixtures, and 13 Tier 1/3 structural tests, two enforcement layers are still missing: the pre-commit hook that blocks commits with hardcoded values (Layer 5 of copium's paradigm) and the CI pipeline split that runs gatekeeper checks in a dedicated parallel job (Layer 0 in CI). Additionally, the gatekeeper test suite lacks Tier 2 synthetic violation tests — the class of tests that creates temporary `.py` files with banned patterns and verifies the checker detects them. Finally, postgres integration tests have no local database service in docker-compose, requiring manual setup.

## What Changes

- **`.pre-commit-config.yaml`** (NEW): Pre-commit hook `ban-test-hardcodes` calling `check-test-hardcodes.sh` with `pass_filenames: false`. Includes ruff check + format hooks covering `src/`, `tests/`, and `main.py`.
- **`.github/workflows/quality.yml`** (REWRITE): Split single monolithic `check` job into 4 parallel jobs: `lint-and-typecheck` (pyright + ruff + black), `unit-tests` (G1 + G2), `integration-tests` (G3 + G4), `gatekeeper` (G5 + checker script). Each job uses the same pytest commands as the Makefile. Adds `tests/` to CI ruff/black/pyright coverage (currently only `src/ main.py`).
- **4 Tier 2 synthetic gatekeeper tests** (NEW, `tests/` root-level): `test_hardcode_checker_core.py` (10 tests, mode-specific banned-pattern detection), `test_hardcode_checker_production_urls.py` (6 tests, production URL always-banned enforcement), `test_boundary_compliance.py` (10 tests, annotation verification + pre-commit/CI config checks), `test_hardcode_checker_regression.py` (8 tests, false-positive prevention + output determinism).
- **`test_conftest_checker_cache.py`** (EXPANDED from 4 to 12 tests): Add hash coverage tests, performance budget tests, and `checker_result("all")` vs direct subprocess comparison.
- **`scripts/check-test-hardcodes.sh`** (MODIFIED): Add 4 new gatekeeper test files to EXCLUDE_FILES for self-exclusion.
- **`docker-compose.yml`** (MODIFIED): Add `test-database` service (PostgreSQL 18, port 5433) for `--run-postgres` integration tests.

## Capabilities

### New Capabilities
- `synthetic-checker-tests`: Tier 2 gatekeeper tests that create temporary `.py` files with banned patterns, invoke `check-test-hardcodes.sh` via direct `subprocess.run()` (not cache), and assert violations are detected. Covers mode-specific detection, production URL always-banned enforcement, boundary annotation removal, regression prevention, and expanded cache fixture meta-tests.
- `pre-commit-hook`: `.pre-commit-config.yaml` with `ban-test-hardcodes` local hook that runs `check-test-hardcodes.sh` on `^tests/` with `pass_filenames: false`, blocking commits containing banned test values. Paired with ruff check + format hooks.
- `ci-pipeline-split`: Split `.github/workflows/quality.yml` from a single monolithic job into 4 parallel jobs (lint-and-typecheck, unit-tests, integration-tests, gatekeeper), each running the same pytest commands as the Makefile's G1-G5 groups. Adds `tests/` to CI linting/typechecking scope.
- `test-database-service`: Docker Compose `test-database` service (PostgreSQL 18 on port 5433) configured with test-safe credentials, enabling local `make test-postgres` integration tests without manual database setup.

### Modified Capabilities
<!-- No spec-level requirement changes. Implementation detail changes only. -->

## Impact

- **`.pre-commit-config.yaml`** — new file, ~35 lines. No dependencies.
- **`.github/workflows/quality.yml`** — rewritten, ~95 lines. Changes CI job structure significantly.
- **`tests/test_hardcode_checker_core.py`** — new file, ~350 lines. Uses `tempfile.NamedTemporaryFile` for synthetic `.py` files, direct `subprocess.run`.
- **`tests/test_hardcode_checker_production_urls.py`** — new file, ~250 lines. Same pattern.
- **`tests/test_boundary_compliance.py`** — new file, ~500 lines. Parses `.pre-commit-config.yaml` and `.github/workflows/quality.yml`. Uses `yaml` stdlib for YAML parsing of pre-commit config.
- **`tests/test_hardcode_checker_regression.py`** — new file, ~300 lines. Same pattern.
- **`tests/test_conftest_checker_cache.py`** — expanded from ~180 to ~400 lines (+8 tests). Uses `time.perf_counter()` for performance budgets.
- **`scripts/check-test-hardcodes.sh`** — +4 lines in EXCLUDE_FILES array.
- **`docker-compose.yml`** — +12 lines, new `test-database` service.
- No production code changes. Pure test infrastructure + CI configuration.
