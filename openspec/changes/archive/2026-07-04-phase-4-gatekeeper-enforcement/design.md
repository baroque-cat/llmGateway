## Context

After Phase 3, llmGateway has a working gatekeeper infrastructure: `check-test-hardcodes.sh` (4 modes, 7 banned-pattern arrays), cached pytest fixtures (`_cached_checker_results`, `checker_result`, `CheckerResult`), and 13 root-level structural tests (Tier 1: clean-codebase, Tier 3: structural integrity). The test suite passes `bash scripts/check-test-hardcodes.sh all` with exit 0.

Two enforcement layers from copium's 6-layer paradigm are still missing:

1. **Pre-commit hook (Layer 5):** No mechanism to block commits containing hardcoded test values before they reach CI. Copium's `ban-test-hardcodes` hook runs the checker authoritatively (no cache) on every commit touching `tests/`.
2. **CI pipeline split (Layer 0 in CI):** The current `.github/workflows/quality.yml` is a single monolithic `check` job running all lint/typecheck/pytest sequentially. Copium uses 5 parallel jobs (simlece, tgcopiumapp-app, tgcopiumapp-gatekeeper, frontend, postgres-integration), with the gatekeeper job running only root-level tests.

Additionally, the gatekeeper test suite lacks **Tier 2 synthetic violation tests** — the class of tests that creates temporary `.py` files with banned patterns and verifies the checker detects them in specific modes. Copium has 4 such files (~73 test functions). Phase 3 created only Tier 1 (clean-codebase verification) and Tier 3 (structural integrity) tests.

Finally, postgres integration tests (`make test-postgres`, `--run-postgres`) have no local database service in `docker-compose.yml`, requiring developers to set up PostgreSQL manually.

## Goals / Non-Goals

**Goals:**
- Create `.pre-commit-config.yaml` with `ban-test-hardcodes` hook + ruff check/format hooks covering `src/`, `tests/`, `main.py`
- Split `.github/workflows/quality.yml` into 4 parallel jobs matching Makefile G1-G5 groups
- Create 4 Tier 2 synthetic violation test files adapting copium's architecture (string concatenation for banned patterns, `tempfile` for synthetic `.py` files, direct `subprocess.run` invocation)
- Expand `test_conftest_checker_cache.py` from 4 to 12 tests with performance budgets and hash coverage
- Add `test-database` service to `docker-compose.yml` (PostgreSQL 18, port 5433, test-safe credentials)
- Update `scripts/check-test-hardcodes.sh` EXCLUDE_FILES to include new test files

**Non-Goals:**
- No `.env` chain changes (completed in Phase 3)
- No new banned-pattern arrays in the checker script
- No stress test changes
- No production code changes
- No Makefile changes (G5 already collects root-level tests via inversion)
- No `pyproject.toml` changes
- No `tests/conftest.py` changes (all gatekeeper fixtures already present)

## Decisions

### D1: Pre-commit hook uses authoritative mode (no cache)

**Rationale:** The `_cached_checker_results` fixture runs the checker once per session for speed in pytest. The pre-commit hook runs the checker directly (`bash scripts/check-test-hardcodes.sh` — defaults to `all` mode) without any cache. This is the authoritative enforcement point: even if a developer bypasses `make test`, the pre-commit hook blocks the commit.

Copium's configuration (`.pre-commit-config.yaml` lines 86-91):
```yaml
- id: ban-test-hardcodes
  name: Ban hardcoded test values
  entry: bash scripts/check-test-hardcodes.sh
  language: system
  files: ^tests/
  pass_filenames: false
```

**Adaptation:** Single-package llmGateway needs only one `ruff` hook (no simlece/tgcopiumapp split). Files pattern covers `^(src|tests|main\.py)/` for ruff, `^tests/` for ban-test-hardcodes.

**Alternatives considered:**
- *Cache-aware hook:* Would require the checker to use the same cache mechanism as pytest fixtures — impossible in a pre-commit context (no pytest process).
- *Separate pyright hook:* Copium has dedicated pyright hooks per package. llmGateway can keep pyright in CI only; adding it to pre-commit would be overly slow for a single hook invocation.

### D2: CI split mirrors Makefile G1-G5 groups

**Rationale:** The Makefile already defines process-isolation groups with `-` prefix conventions (G1 = gate, G2-G5 = fault-tolerant). Copying these exact commands into CI jobs ensures consistency between local `make test` and CI `pytest` invocations.

Job structure:

| CI Job | Makefile Groups | Tests Coverage |
|--------|----------------|----------------|
| `lint-and-typecheck` | — | pyright `src/ main.py` + ruff `src/ tests/ main.py` + black `src/ tests/ main.py` |
| `unit-tests` | G1 + G2 | `tests/unit/` excluding config, then `tests/unit/config/` |
| `integration-tests` | G3 + G4 | `tests/integration/ tests/security/ tests/e2e/`, then `tests/batching/` |
| `gatekeeper` | G5 | `tests/ --ignore=...` (inversion) + `check-test-hardcodes.sh all` |

**Key change from current CI:** `tests/` folder is added to ruff/black/pyright scope. Currently CI only checks `src/ main.py`.

**Alternatives considered:**
- *Single job with sequential steps:* Current state. Loses parallelism and fails all-at-once on gatekeeper violations.
- *5 jobs (separate G3 and G4):* Copium separates app tests and gatekeeper. For llmGateway, G3 and G4 are both fault-tolerant and small — combining them simplifies the CI config.

### D3: Synthetic test files use _gate_synth_ prefix for temp files

**Rationale:** Copium's `test_hardcode_checker_core.py` uses `_core_synth_` prefix to avoid the `_cleanup_stale_temp_files` autouse fixture (which removes `tmp*.py`). The prefix prevents premature cleanup.

For llmGateway, use `_gate_synth_` prefix:
```python
def _make_temp_py(directory: Path, content: str) -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", prefix="_gate_synth_", suffix=".py",
        dir=str(directory), delete=False, encoding="utf-8",
    )
    tmp.write(content)
    tmp.close()
    return tmp.name
```

This avoids both `_cleanup_stale_temp_files` (which removes `tmp*.py`) and the checker's own scan (files self-destruct on test teardown).

**Alternatives considered:**
- *`tmp` prefix + cleanup skipping:* More fragile — would need to add `_gate_synth_` to `_cleanup_stale_temp_files` or manage cleanup manually.
- *Single shared temp directory:* Copium's approach of placing temp files directly in the test directory they're simulating (e.g., `tests/unit/` for canonical mode, `tests/integration/` for boundary) ensures the checker scans them naturally.

### D4: String concatenation for banned patterns in test source

**Rationale:** The gatekeeper test files themselves are root-level `.py` files, scanned by `check_root()` mode. To avoid self-triggering, banned patterns must be constructed via string concatenation:
```python
_BANNED_MODEL = '"gpt-' + '4"'
_BANNED_URL = "api.open" + "ai.com"
_BOUNDARY_ANNO = "#" + " boundary:"
```

This is the exact pattern copium uses (documented in `test_hardcode_checker_core.py` lines 19-23).

**Alternatives considered:**
- *Add test files to EXCLUDE_FILES:* Already done. But even with exclusion, using raw banned strings in test assertions (`assert "gpt-4" in output`) could match other files' content — concatenation is cleaner.
- *Base64 encoding:* Overly complex for bash-grep-based checking. Not copium's pattern.

### D5: test_boundary_compliance.py parses YAML configs for structural checks

**Rationale:** Copium's `test_boundary_compliance.py` (1034 lines) includes `TestPrecommitBanTestHardcodesHook` and `TestCIWorkflowGatekeeperStep` classes that parse `.pre-commit-config.yaml` and `.github/workflows/ci.yml` via `yaml.safe_load()`. This ensures the pre-commit hook and CI workflow are structurally correct.

For llmGateway, use Python's stdlib `yaml` (already available) to parse both files and verify:
- Pre-commit: `ban-test-hardcodes` hook exists with correct `entry`, `files`, `pass_filenames`
- CI: `gatekeeper` job exists, runs checker script + G5 pytest

### D6: Docker test-database service uses port 5433

**Rationale:** The production database service uses port 5432. A separate `test-database` service on port 5433 avoids conflicts when both production and test databases are needed simultaneously. Credentials match the test-safe values from CanonicalConfig: `test_user` / `test_password` / `test_db`.

```yaml
test-database:
  image: postgres:18-alpine
  environment:
    POSTGRES_USER: test_user
    POSTGRES_PASSWORD: test_password
    POSTGRES_DB: test_db
  ports:
    - "5433:5432"
```

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|------|------------|------------|
| Pre-commit hook produces false positives on first run | Medium | EXCLUDE_FILES already covers all gatekeeper test files (58 entries). New test files use string concatenation. Run `pre-commit run ban-test-hardcodes --all-files` to verify. |
| CI gatekeeper job fails because checker script isn't executable | Low | Script is already committed with `chmod +x`. CI checkout preserves permissions. |
| Synthetic test files not cleaned up, polluting scan directories | Low | `delete=False` + explicit `os.unlink()` in teardown. Copium's pattern is proven. |
| test_boundary_compliance.py parametrized tests multiply runtime | Medium | Copium parametrizes over 31 boundary files (~60s). llmGateway has fewer boundary files (~15) — estimated ~30s. |
| Performance budget tests flake on slow CI runners | Low | Budgets are generous (hash < 1.0s, cache startup < 10.0s). Copium validated these across CI and local dev. |
| Docker test-database port conflicts with host PostgreSQL | Medium | Use port 5433 (non-standard for production) to avoid conflicts. Document in TESTING-RUN.md. |
| CI splitting increases GitHub Actions minutes | Low | 4 parallel jobs complete faster overall than 1 sequential job, offsetting the per-job overhead. |
| CI ruff/black now scan `tests/` — may reveal pre-existing lint issues | Medium | Run `make lint` first to baseline. Address any issues before enabling CI coverage. |

## Open Questions

- Should `test_boundary_compliance.py` verify per-file banned-pattern mappings for boundary directories, or just verify the checker passes on the clean codebase? **Decision: start with clean-codebase verification (simpler), add per-file mappings in a follow-up if needed.**
- Should the CI `gatekeeper` job use `make test-gatekeeper` or the raw pytest command? **Decision: use raw pytest command matching G5 exactly, to avoid Makefile dependency in CI.**
