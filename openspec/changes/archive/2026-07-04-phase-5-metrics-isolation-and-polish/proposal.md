## Why

After Phases 1-4, the project has adopted all 6 layers of copium's test paradigm: process isolation (Makefile G1-G6), per-test timeouts, CanonicalConfig-driven environment, marker-based grouping, the gatekeeper infrastructure (script + cache fixtures + 13 Tier 1/2/3 tests), pre-commit hooks, CI pipeline split, and TESTING documentation. However, Phase H (metrics fixture deduplication) from the original blueprint was never executed, 3 gatekeeper test files from Phase J are still missing, and several infrastructure improvements from copium's pre-commit and CI configuration are absent.

## What Changes

- **Metrics fixture deduplication (Phase H):** Create shared `tests/unit/metrics/conftest.py` with an `_isolate_metrics_collector` autouse fixture using `monkeypatch.delenv()` (pytest-native) instead of the current `os.environ.pop()` pattern. Consolidate 4 duplicated near-identical autouse fixtures from `test_metrics_factory.py`, `test_memory_backend.py`, `test_keeper_metrics.py`, and `test_keeper_metrics_endpoint.py`. Add equivalent fixture to `tests/integration/conftest.py`. Improve `test_prometheus_backend.py` to use the shared fixture instead of `_make_unique_name()` counter and `__new__()` hacks.
- **Missing gatekeeper tests (Phase J2, J6, J8):** Create `test_security.py` (hardcoded tokens/keys in source, `.gitignore` verification), `test_ci_pipeline.py` (detailed CI workflow structural validation), and `test_layer_import_scan.py` (AST-based import boundary enforcement between architectural layers).
- **Pre-commit infrastructure polish:** Add 8 file-hygiene hooks (trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, check-merge-conflict, detect-private-key, mixed-line-ending), pyright in pre-commit (`src/` only), and shellcheck for `scripts/`.
- **Scheduled CI runs:** Add `schedule: cron: '0 3 * * *'` trigger to `quality.yml` for nightly test runs.

## Capabilities

### New Capabilities
- `metrics-fixture-dedup`: Shared autouse fixture for metrics collector isolation in `tests/unit/metrics/conftest.py`, replacing 4 duplicated inline fixtures with a single `monkeypatch.delenv()`-based implementation.
- `security-gatekeeper-tests`: Structural security tests (`test_security.py`) verifying no hardcoded tokens/keys in source, `.gitignore` covers `.env`, no committed credentials.
- `ci-pipeline-gatekeeper-tests`: Detailed CI workflow validation (`test_ci_pipeline.py`) checking job structure, step ordering, conditions, and tool versions.
- `layer-import-gatekeeper-tests`: AST-based import boundary enforcement (`test_layer_import_scan.py`) verifying architectural layering constraints (e.g., `src/config/` does not import from `src/db/`).

### Modified Capabilities
- `pre-commit-hook`: Add 8 file-hygiene hooks, pyright hook for `src/`, and shellcheck hook for `scripts/`.
- `ci-pipeline-split`: Add `schedule` trigger with nightly cron for regular test runs.

## Impact

- **`tests/unit/metrics/conftest.py`** — new file (~25 lines). Shared autouse fixture for metrics isolation.
- **`tests/unit/conftest.py`** — new file (~15 lines). Re-exports metrics fixture for subdirectories.
- **`tests/integration/conftest.py`** — modified (+20 lines). Add equivalent fixture for integration tests.
- **`tests/unit/metrics/test_metrics_factory.py`** — modified (−12 lines). Remove duplicated inline fixture.
- **`tests/unit/metrics/test_memory_backend.py`** — modified (−10 lines). Remove duplicated inline fixture.
- **`tests/unit/services/test_keeper_metrics.py`** — modified (−10 lines). Remove duplicated inline fixture.
- **`tests/unit/metrics/test_prometheus_backend.py`** — modified (~30 lines). Replace `_make_unique_name()` with shared fixture.
- **`tests/test_security.py`** — new file (~200 lines). Structural security tests.
- **`tests/test_ci_pipeline.py`** — new file (~250 lines). CI workflow validation.
- **`tests/test_layer_import_scan.py`** — new file (~300 lines). Import boundary enforcement.
- **`.pre-commit-config.yaml`** — modified (+29 lines). File hygiene + pyright + shellcheck hooks.
- **`.github/workflows/quality.yml`** — modified (+2 lines). Scheduled nightly CI trigger.
- **`scripts/check-test-hardcodes.sh`** — modified (+3 EXCLUDE_FILES entries for new gatekeeper tests).
- No production code changes. Pure test infrastructure + configuration.
