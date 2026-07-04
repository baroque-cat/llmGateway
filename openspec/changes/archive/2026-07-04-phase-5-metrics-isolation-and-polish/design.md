## Context

After Phase 4, llmGateway has adopted all 6 layers of copium's test paradigm. However, two items from the original `problem_tests.md` blueprint remain unaddressed:

1. **Phase H (metrics fixture deduplication):** Four near-identical autouse fixtures (`_clean_env_and_singleton`, `_isolate_collector_for_memory_backend`, `_isolate_collector`) are copy-pasted across `tests/unit/metrics/`, `tests/unit/services/`, and `tests/integration/`. All do the same thing: `reset_collector()` + raw `os.environ.pop()` for `METRICS_BACKEND` and `PROMETHEUS_MULTIPROC_DIR` before and after `yield`. None use `monkeypatch`, so env mutations are not pytest-native and interact subtly with the root conftest's `monkeypatch.setenv`.

2. **Phase J (3 missing gatekeeper tests):** `test_security.py`, `test_ci_pipeline.py`, and `test_layer_import_scan.py` were in the blueprint but never created. Phase 3 and 4 created 13 of 16 planned gatekeeper tests plus 5 extras not in the blueprint.

Additionally, exploration of copium's pre-commit configuration revealed several infrastructure improvements llmGateway does not have: file-hygiene hooks (8 standard pre-commit hooks), pyright in pre-commit, shellcheck for shell scripts, and a scheduled CI trigger.

## Goals / Non-Goals

**Goals:**
- Consolidate 4 duplicated metrics isolation autouse fixtures into a single shared fixture using `monkeypatch.delenv()`
- Create 3 missing gatekeeper test files (`test_security.py`, `test_ci_pipeline.py`, `test_layer_import_scan.py`)
- Add 8 file-hygiene pre-commit hooks (trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-json, check-merge-conflict, detect-private-key, mixed-line-ending)
- Add pyright and shellcheck to pre-commit
- Add nightly scheduled CI trigger
- Improve `test_prometheus_backend.py` to use shared fixture instead of `_make_unique_name()` workaround

**Non-Goals:**
- No production code changes (`src/` is untouched)
- No new banned-pattern arrays in the gatekeeper script
- No Makefile changes
- No docker-compose changes
- No conftest.py root-level changes
- No CanonicalConfig changes
- No extensive conftest meta-tests (copium has 1822 lines of these; out of scope)

## Decisions

### D1: Shared fixture lives in `tests/unit/metrics/conftest.py` + re-exported from `tests/unit/conftest.py`

**Rationale:** Pytest automatically applies conftest fixtures from ancestor directories. Placing `_isolate_metrics_collector` in `tests/unit/metrics/conftest.py` covers all 6 files in `tests/unit/metrics/`. Creating `tests/unit/conftest.py` (which re-imports the same fixture) extends coverage to `tests/unit/services/test_keeper_metrics.py`. For `tests/integration/test_keeper_metrics_endpoint.py`, a parallel fixture is added to the existing `tests/integration/conftest.py`.

This mirrors copium's `tgcopiumapp/tests/webapp/conftest.py` pattern (shared `mock_accessor`/`mock_pipeline` fixtures for the webapp directory).

**Alternatives considered:**
- *Single `tests/conftest.py` fixture:* Root conftest would affect ALL 100+ test files including stress/e2e — unnecessary overhead. Scope is too broad.
- *`tests/_metrics_isolation.py` helper module:* More flexible but introduces a non-standard import pattern. Copium's conftest hierarchy approach is simpler and pytest-native.
- *Remove all per-test isolation and fix the singleton:* The `get_collector()` singleton caches the collector instance. Making it fully stateless would require changing production code in `src/metrics/__init__.py` — out of scope.

### D2: Use `monkeypatch.delenv()` instead of `os.environ.pop()`

**Rationale:** The current fixtures mutate `os.environ` directly via `os.environ.pop(key, None)`. This is fragile because the root conftest's `_set_config_vars_from_canonical` sets `METRICS_BACKEND=""` and `PROMETHEUS_MULTIPROC_DIR=""` via `monkeypatch.setenv` before every test. Direct `os.environ.pop()` removes these monkeypatched values, forcing the collector factory to read whatever is in the real environment.

`monkeypatch.delenv(raising=False)` is pytest-native — it removes the monkeypatched value and auto-restores it after the test. No risk of leaking state between tests.

**Alternatives considered:**
- *Keep `os.environ.pop()`:* Works today but relies on implicit restoration via root conftest's `monkeypatch.setenv` re-setting the values on next test. Fragile ordering dependency.

### D3: Pyright in pre-commit covers `src/` only, not `tests/`

**Rationale:** Copium has 5 pyright pre-commit hooks (per-package, with varying strictness). Running full pyright on `tests/` in pre-commit would be prohibitively slow (3550+ errors exist in test files). The CI `lint-and-typecheck` job already runs pyright on `src/ main.py`.

By limiting pre-commit pyright to `src/ main.py`, we catch type errors early without slowing down commits.

**Alternatives considered:**
- *Full pyright including tests:* Too slow for pre-commit; existing errors would block all commits.
- *No pyright in pre-commit:* Current state; type errors are only caught in CI.

### D4: Shellcheck covers `scripts/` directory

**Rationale:** `check-test-hardcodes.sh` is a 472-line bash script. Shellcheck catches common shell scripting errors (unquoted variables, word splitting, etc.). Copium already uses this hook.

### D5: `test_layer_import_scan.py` uses `ast.parse()` for static analysis

**Rationale:** Architectural layer boundaries are enforced at the import level. Python's `ast` module allows static analysis of all `.py` files without executing them. This is a Tier 3 structural gatekeeper test — no cache fixtures needed.

The test scans `src/` directories and verifies that no module imports from forbidden layers (e.g., `src/config/` must not import from `src/db/` or `src/services/`).

### D6: Scheduled CI runs daily at 03:00 UTC

**Rationale:** Copium uses `cron: '0 3 * * *'` for nightly test runs. This catches regressions from dependency updates or external service changes. Same schedule for llmGateway — off-peak hours.

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|------|------------|------------|
| Shared fixture breaks tests that relied on specific `os.environ` state | Low | The new fixture uses `monkeypatch.delenv` which is more predictable. All existing tests pass with the old inline fixtures; migrating to shared should be a no-op. |
| `check-yaml` pre-commit hook fails on existing YAML files | Low | `check-yaml` validates syntax only, not schema. All existing YAML files (`docker-compose.yml`, `quality.yml`, `.pre-commit-config.yaml`, `config/*.yaml`) parse cleanly. |
| `shellcheck` produces false positives on the gatekeeper script | Low | The script is well-structured (set -euo pipefail, functions, arrays). Shellcheck rarely false-positives on bash scripts. |
| `trailing-whitespace` / `end-of-file-fixer` produce large diffs on first run | Medium | Run `pre-commit run --all-files` once and commit the auto-fixes separately. |
| Pyright in pre-commit slows down commits | Low | Only runs on `src/` (not `tests/`), and only when files under `src/` change. |
| `test_layer_import_scan.py` has false positives for legitimate imports | Medium | The test should check for violations, not just any import. Use a whitelist of allowed cross-layer imports and only flag unexpected ones. |
| `test_security.py` finds pre-existing issues | Low | The gatekeeper script already bans most secrets in test files. This test scans `src/` for patterns not covered by the script. |
