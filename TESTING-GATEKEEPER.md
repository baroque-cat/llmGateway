# Testing Gatekeeper — Hardcode Checker Infrastructure

> Architecture of the zero-hardcodes enforcement system.

## Overview

The gatekeeper is a two-layer enforcement system:

1. **Shell script** (`scripts/check-test-hardcodes.sh`) — scans test files for
   banned patterns in 4 modes.
2. **Pytest fixtures** (`tests/conftest.py`) — cache script results and provide
   them to structural tests.

## Script Architecture

### 4 Modes

| Mode | Scope | Strictness | Boundary annotations |
| --- | --- | --- | --- |
| `canonical` | `tests/unit/` | Strict — any match is a violation | Ignored |
| `boundary` | `tests/integration/`, `tests/security/`, `tests/e2e/`, `tests/stress/`, `tests/batching/` | Whitelist — `# boundary:` exempts | Honored (20-line lookback) |
| `root` | `tests/*.py` (root-level only) | Strict — any match is a violation | Ignored |
| `all` | All of the above | Composite — runs canonical → boundary → root | Mixed |

### Usage

```bash
# Run all modes (default)
bash scripts/check-test-hardcodes.sh all

# Run a specific mode
bash scripts/check-test-hardcodes.sh canonical
bash scripts/check-test-hardcodes.sh boundary
bash scripts/check-test-hardcodes.sh root

# No args defaults to "all"
bash scripts/check-test-hardcodes.sh
```

### Output format

```
CANONICAL VIOLATION: tests/unit/services/test_gateway.py:42: pattern 'gpt-4'
BOUNDARY VIOLATION: tests/integration/test_api.py:15: pattern 'https://api.openai.com' without # boundary: annotation
ROOT VIOLATION: tests/test_foo.py:7: pattern 'DB_USER=llm_gateway'
```

When all modes pass:

```
All test hardcode checks passed
```

## Banned-Pattern Arrays

The script defines 7 arrays of prohibited values:

### 1. BANNED_PROD_URLS (6 patterns)

Production API URLs — **always banned in all modes**, even with `# boundary:`.

| Pattern | Provider |
| --- | --- |
| `https://generativelanguage.googleapis.com` | Gemini |
| `https://api.anthropic.com` | Anthropic |
| `https://api.deepseek.com` | DeepSeek |
| `https://dashscope.aliyuncs.com` | Qwen |
| `https://api.openai.com` | OpenAI |
| `https://api.groq.com` | Groq |

### 2. BANNED_SECRETS (2 patterns)

Placeholder secrets from `.env.example` — must never appear in test files.

| Pattern | Source |
| --- | --- |
| `your_secure_password_here` | `.env.example` DB_PASSWORD |
| `your_secure_metrics_token_here` | `.env.example` METRICS_ACCESS_TOKEN |

### 3. BANNED_DB_PARAMS (3 patterns)

Production DB parameter values — tests must use `test_user`/`test_password`/`test_db`.

| Pattern | Env Var |
| --- | --- |
| `DB_HOST=database` | DB_HOST |
| `DB_USER=llm_gateway` | DB_USER |
| `DB_NAME=llmgateway` | DB_NAME |

### 4. BANNED_GATEWAY_PORTS (5 patterns)

Non-canonical gateway ports — only `55300` is allowed.

| Pattern | Reason |
| --- | --- |
| `GATEWAY_PORT=8000` | Uvicorn default |
| `GATEWAY_PORT=8080` | Common HTTP port |
| `GATEWAY_PORT=3000` | Node.js default |
| `GATEWAY_PORT=5000` | Flask default |
| `GATEWAY_PORT=9000` | Alternative |

### 5. BANNED_PROVIDER_TYPES_REGEX (6 patterns)

Invalid provider type strings — must use `openai_like`, not `openai`.

| Pattern | Correct value |
| --- | --- |
| `provider_type.*"openai"` | `openai_like` |
| `provider_type.*"deepseek"` | `openai_like` |
| `provider_type.*"qwen"` | `openai_like` or `gemini` |
| `provider_type.*"groq"` | `openai_like` |
| `provider_type.*"claude"` | `anthropic` |
| `provider_type.*"google"` | `gemini` |

### 6. BANNED_MODEL_NAMES (6 patterns)

Obsolete or non-canonical model names.

| Pattern | Reason |
| --- | --- |
| `"gpt-3.5-turbo"` | Obsolete OpenAI model |
| `"gpt-4"` | Non-canonical |
| `"gpt-4o"` | Non-canonical |
| `"claude-3-opus"` | Obsolete Anthropic naming |
| `"claude-3-sonnet"` | Obsolete Anthropic naming |
| `"deepseek-coder"` | Non-canonical |

### 7. BANNED_OTHER_REGEX (2 patterns)

| Pattern | Reason |
| --- | --- |
| `password="test_secret"` | Non-canonical test password |
| `PROMETHEUS_MULTIPROC_DIR=` | Should not be hardcoded in tests |

## Boundary Lookback Algorithm

In boundary mode, when a banned pattern is found without a same-line `# boundary:`
annotation, the script looks back up to 20 non-blank lines:

1. **Same-line check**: Does the line contain `# boundary:` (case-insensitive)?
2. **Lookback**: Scan the preceding 20 non-blank lines for `# boundary:`.
3. **Skip**: Blank lines, comment-only lines, and docstring lines are not counted
   toward the 20-line window.
4. **Result**: If `# boundary:` is found → allowed. If not → `BOUNDARY VIOLATION`.

## EXCLUDE_FILES

The script skips these files entirely:

- **Infrastructure**: `conftest.py`, `_canonical.py`, `_constants.py`
- **Self-exclusion**: All gatekeeper test files (`test_*.py` at root level)
- **Pre-existing violations**: Files that use banned patterns for legitimate
  testing purposes (e.g. `"gpt-4"` as a test fixture for error handling)

## Cache Fixtures (3-Layer Chain)

### Layer 1: `_cached_checker_results` (session-scoped)

Runs `check-test-hardcodes.sh` once per mode (`canonical`, `boundary`, `root`)
at the start of the test session. Results are stored as `CheckerResult` named
tuples in a `types.MappingProxyType` (read-only).

```python
@pytest.fixture(scope="session")
def _cached_checker_results() -> _CheckerCache:
    results: dict[str, CheckerResult] = {}
    for mode in ("canonical", "boundary", "root"):
        proc = subprocess.run(["bash", str(_CHECKER_SCRIPT), mode], ...)
        results[mode] = CheckerResult(proc.returncode, proc.stdout, proc.stderr)
    return types.MappingProxyType(results)
```

### Layer 2: `checker_result` (function-scoped accessor)

Returns a callable that accepts a mode string and returns the cached
`CheckerResult`. The `"all"` mode is composed from the three cached results
(max returncode, deduplicated stdout).

```python
def test_checker_passes(checker_result):
    result = checker_result("all")
    assert result.returncode == 0
```

### Layer 3: `CheckerResult` (NamedTuple)

```python
class CheckerResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
```

### Auxiliary fixtures

- `_cleanup_stale_temp_files` (session autouse) — removes `tmp*.py` from scan dirs
- `_compute_checker_hash()` — sha256 of script + all scanned `.py` files

## Test Classification (3 Tiers)

### Tier 1: Clean-codebase tests

Verify that the gatekeeper script passes on the current codebase.

```python
def test_checker_canonical_passes(checker_result):
    assert checker_result("canonical").returncode == 0
```

### Tier 2: Synthetic violation tests

Create temporary files with known violations, run the script, verify it catches
them, then clean up.

```python
def test_checker_detects_banned_model(tmp_path):
    # Create a temp file with a banned model name
    # Run the script
    # Assert non-zero return code
    # Clean up
```

### Tier 3: Consistency tests

Verify that documentation, Makefile, and project structure are consistent with
the test infrastructure.

```python
def test_makefile_has_6_groups():
    # Parse Makefile, verify G1-G6 exist with correct flags
```

## Enforcement Layers

| Layer | What | When |
| --- | --- | --- |
| **Shell script** | `check-test-hardcodes.sh` | Manual or via fixtures |
| **Pytest fixtures** | `_cached_checker_results` | Every test session (G5) |
| **Structural tests** | `tests/test_*.py` | G5 root-level tests |
| **CI pipeline** | `make ci` | Every push |
