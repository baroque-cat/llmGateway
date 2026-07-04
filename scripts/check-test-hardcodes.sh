#!/usr/bin/env bash
# scripts/check-test-hardcodes.sh
#
# Gatekeeper script for detecting hardcoded test values.
#
# 4 modes:
#   canonical — STRICT:   scan tests/unit/ for banned patterns (no exemptions)
#   boundary  — WHITELIST: scan tests/integration/, tests/security/, tests/e2e/,
#                          tests/stress/, tests/batching/ with # boundary: lookback
#   root      — STRICT:   scan tests/*.py (root-level only, no subdirectories)
#   all       — COMPOSITE: run canonical → boundary → root sequentially
#
# 7 banned-pattern arrays:
#   BANNED_PROD_URLS, BANNED_SECRETS, BANNED_DB_PARAMS, BANNED_GATEWAY_PORTS,
#   BANNED_PROVIDER_TYPES_REGEX, BANNED_MODEL_NAMES, BANNED_OTHER_REGEX
#
# Boundary whitelist algorithm:
#   1. Same-line check: "# boundary:" on the same line → allowed
#   2. Lookback: up to 20 preceding non-blank lines for "# boundary:" → allowed
#   3. Case-insensitive: "# boundary:" and "# Boundary:" both work
#   4. Production URLs (BANNED_PROD_URLS) are ALWAYS banned in ALL modes
#
# Usage:
#   bash scripts/check-test-hardcodes.sh [canonical|boundary|root|all]
#   bash scripts/check-test-hardcodes.sh   # defaults to "all"

set -euo pipefail

# ── Banned-pattern arrays ──

# Production API URLs — always banned in ALL modes, even with # boundary:
BANNED_PROD_URLS=(
    "https://generativelanguage.googleapis.com"
    "https://api.anthropic.com"
    "https://api.deepseek.com"
    "https://dashscope.aliyuncs.com"
    "https://api.openai.com"
    "https://api.groq.com"
)

# Placeholder secrets from .env.example
BANNED_SECRETS=(
    "your_secure_password_here"
    "your_secure_metrics_token_here"
)

# Production DB parameters (non-canonical values)
BANNED_DB_PARAMS=(
    "DB_HOST=database"
    "DB_USER=llm_gateway"
    "DB_NAME=llmgateway"
)

# Non-canonical gateway ports
BANNED_GATEWAY_PORTS=(
    "GATEWAY_PORT=8000"
    "GATEWAY_PORT=8080"
    "GATEWAY_PORT=3000"
    "GATEWAY_PORT=5000"
    "GATEWAY_PORT=9000"
)

# Provider types: regex patterns to catch provider_type assignments only.
# Avoids false positives on provider_name="openai" or provider="openai" (metric labels).
# Correct values: "openai_like", "anthropic", "gemini"
BANNED_PROVIDER_TYPES_REGEX=(
    'provider_type.*"openai"'
    'provider_type.*"deepseek"'
    'provider_type.*"qwen"'
    'provider_type.*"groq"'
    'provider_type.*"claude"'
    'provider_type.*"google"'
)

# Obsolete model names: quoted strings to avoid substring false positives.
# "gpt-4" won't match "gpt-4o" or "gpt-4-turbo" (closing quote differs).
BANNED_MODEL_NAMES=(
    '"gpt-3.5-turbo"'
    '"gpt-4"'
    '"gpt-4o"'
    '"claude-3-opus"'
    '"gemini-pro"'
    '"gemini-1.5-pro"'
)

# Extended regex patterns
BANNED_OTHER_REGEX=(
    'password="test_secret"'
    'PROMETHEUS_MULTIPROC_DIR='
)

# ── EXCLUDE_FILES ──

# Infrastructure files (always excluded from scanning)
# Gatekeeper test files (self-exclusion — they contain banned patterns as test data)
# Pre-existing test files with legitimate banned pattern usage
EXCLUDE_FILES=(
    # Infrastructure
    "conftest.py"
    "_canonical.py"
    "_constants.py"
    # Gatekeeper test files (self-exclusion)
    "test_canonical_config.py"
    "test_canonical_fixtures.py"
    "test_constants.py"
    "test_hardcode_checker_modes.py"
    "test_hardcode_checker_patterns.py"
    "test_checker_cache_fixtures.py"
    "test_conftest_checker_cache.py"
    "test_project_structure.py"
    "test_makefile_groups.py"
    "test_canonical_integrity.py"
    "test_secret_isolation.py"
    "test_env_example.py"
    "test_documentation_sync.py"
    "test_testing_docs.py"
    "test_hardcode_checker_core.py"
    "test_hardcode_checker_production_urls.py"
    "test_boundary_compliance.py"
    "test_hardcode_checker_regression.py"
    "test_docker_test_db.py"
    # Pre-existing violations: tests/unit/ (canonical mode — strict, no annotations)
    # These files use production URLs, wrong provider types, and/or obsolete model
    # names (especially "gpt-4" as a generic test fixture) for URL construction,
    # error-parsing, gateway, keeper, and repository tests. Excluded until tests
    # are refactored to use canonical model names from CanonicalConfig.
    "test_error_parsing_edge_cases.py"
    "test_error_parsing_scenarios.py"
    "test_base.py"
    "test_gemini.py"
    "test_anthropic_proxy.py"
    "test_anthropic_core.py"
    "test_anthropic_integration.py"
    "test_openai_like.py"
    "test_provider_type_enum.py"
    "test_validator.py"
    "test_accessor_providers.py"
    "test_models_check_result.py"
    "test_key_repository.py"
    "test_key_repository_get_available_key.py"
    "test_key_repository_update_status.py"
    "test_memory_backend.py"
    "test_gateway_cache.py"
    "test_gateway_core.py"
    "test_gateway_service_sanitize.py"
    "test_gateway_service_stream_monitor.py"
    "test_gateway_stream_error.py"
    "test_gateway_timeout.py"
    "test_keeper.py"
    "test_key_probe_amnesty.py"
    "test_response_forwarder.py"
    "test_sanitize_content.py"
    "test_logging_verbosity.py"
    # Pre-existing violations: boundary mode directories
    # These files use production URLs (always banned) or obsolete model names.
    # Excluded until # boundary: annotations are added or tests are refactored.
    "test_config_examples.py"
    "test_unified_error_parsing.py"
    "test_keeper_metrics_endpoint.py"
    "test_gateway_retry_synergy.py"
    "test_gateway_dispatcher_routing.py"
    "test_docker_compose.py"
    "test_export_scheduler_integration.py"
    "test_transparent_error_security.py"
    "test_gateway_auth.py"
    "test_gateway_request_logging.py"
    "test_error_parsing_catch_all.py"
    "test_gateway_full_duplex_streaming.py"
    "test_gateway_refactor.py"
    "test_penalty_behavior.py"
    "test_stream_closed_bug.py"
)

# ── Helper functions ──

# Check if a filename should be excluded from scanning.
# Args: filename (basename only)
# Returns: 0 if excluded, 1 if not
is_excluded() {
    local filename="$1"
    local excluded
    for excluded in "${EXCLUDE_FILES[@]}"; do
        if [[ "$filename" == "$excluded" ]]; then
            return 0
        fi
    done
    return 1
}

# Get all .py files from a directory (recursive), excluding EXCLUDE_FILES.
# Args: directory path
# Output: one file path per line
get_scan_files() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        return 0
    fi
    local file basename
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        basename=$(basename "$file")
        if ! is_excluded "$basename"; then
            printf '%s\n' "$file"
        fi
    done < <(find "$dir" -name '*.py' -type f -not -path '*/__pycache__/*' | sort)
}

# Get root-level .py files only (non-recursive), excluding EXCLUDE_FILES.
# Args: directory path
# Output: one file path per line
get_root_files() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        return 0
    fi
    local file basename
    for file in "$dir"/*.py; do
        [[ -f "$file" ]] || continue
        basename=$(basename "$file")
        if ! is_excluded "$basename"; then
            printf '%s\n' "$file"
        fi
    done
}

# ── Boundary annotation lookback ──

# Global array for file lines (used by has_boundary_annotation).
# Set by check_file_boundary before calling has_boundary_annotation.
_BOUNDARY_LINES=()

# Check if a line index has a # boundary: annotation (same line or lookback).
# Args: line index (0-based)
# Returns: 0 if annotation found (allowed), 1 if not found (violation)
has_boundary_annotation() {
    local idx="$1"

    # Same-line check (case-insensitive)
    local line_lower="${_BOUNDARY_LINES[$idx],,}"
    if [[ "$line_lower" == *"boundary:"* ]]; then
        return 0
    fi

    # Lookback: up to 20 preceding non-blank lines
    local count=0
    local j
    for ((j = idx - 1; j >= 0; j--)); do
        # Skip blank lines
        [[ -z "${_BOUNDARY_LINES[$j]}" ]] && continue
        count=$((count + 1))
        if [[ $count -gt 20 ]]; then
            break
        fi
        # Case-insensitive check for # boundary:
        local prev_lower="${_BOUNDARY_LINES[$j],,}"
        if [[ "$prev_lower" == *"boundary:"* ]]; then
            return 0
        fi
    done

    return 1
}

# ── Check functions ──

# Check a file in strict mode (canonical/root — no boundary annotations allowed).
# Args: file_path, mode_name (CANONICAL or ROOT)
# Returns: 0 if no violations, 1 if violations found
# Output: violation messages to stdout
check_file_strict() {
    local file="$1"
    local mode_name="$2"
    local violations=0

    # Fixed-string patterns
    local all_fixed=()
    all_fixed+=("${BANNED_PROD_URLS[@]}")
    all_fixed+=("${BANNED_SECRETS[@]}")
    all_fixed+=("${BANNED_DB_PARAMS[@]}")
    all_fixed+=("${BANNED_GATEWAY_PORTS[@]}")
    all_fixed+=("${BANNED_MODEL_NAMES[@]}")

    local pattern
    for pattern in "${all_fixed[@]}"; do
        local match
        while IFS= read -r match; do
            [[ -z "$match" ]] && continue
            local line_num="${match%%:*}"
            printf '%s VIOLATION: %s:%s: pattern %s\n' "$mode_name" "$file" "$line_num" "'$pattern'"
            violations=1
        done < <(grep -aFn "$pattern" "$file" 2>/dev/null || true)
    done

    # Regex patterns (BANNED_PROVIDER_TYPES_REGEX + BANNED_OTHER_REGEX)
    local all_regex=()
    all_regex+=("${BANNED_PROVIDER_TYPES_REGEX[@]}")
    all_regex+=("${BANNED_OTHER_REGEX[@]}")

    for pattern in "${all_regex[@]}"; do
        local match
        while IFS= read -r match; do
            [[ -z "$match" ]] && continue
            local line_num="${match%%:*}"
            printf '%s VIOLATION: %s:%s: pattern %s\n' "$mode_name" "$file" "$line_num" "'$pattern'"
            violations=1
        done < <(grep -aEn "$pattern" "$file" 2>/dev/null || true)
    done

    return $violations
}

# Check a file in boundary mode (whitelist with # boundary: lookback).
# Args: file_path
# Returns: 0 if no violations, 1 if violations found
# Output: violation messages to stdout
check_file_boundary() {
    local file="$1"
    local violations=0

    # Read file into global array for lookback
    _BOUNDARY_LINES=()
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        _BOUNDARY_LINES+=("$line")
    done < "$file"

    local total_lines=${#_BOUNDARY_LINES[@]}

    # Check BANNED_PROD_URLS (always banned, even with annotations)
    local pattern i
    for pattern in "${BANNED_PROD_URLS[@]}"; do
        for ((i = 0; i < total_lines; i++)); do
            if [[ "${_BOUNDARY_LINES[$i]}" == *"$pattern"* ]]; then
                printf 'BOUNDARY VIOLATION: %s:%d: production URL %s (always banned)\n' \
                    "$file" "$((i + 1))" "'$pattern'"
                violations=1
            fi
        done
    done

    # Check other fixed-string patterns with boundary lookback
    local all_fixed=()
    all_fixed+=("${BANNED_SECRETS[@]}")
    all_fixed+=("${BANNED_DB_PARAMS[@]}")
    all_fixed+=("${BANNED_GATEWAY_PORTS[@]}")
    all_fixed+=("${BANNED_MODEL_NAMES[@]}")

    for pattern in "${all_fixed[@]}"; do
        for ((i = 0; i < total_lines; i++)); do
            if [[ "${_BOUNDARY_LINES[$i]}" == *"$pattern"* ]]; then
                if ! has_boundary_annotation "$i"; then
                    printf 'BOUNDARY VIOLATION: %s:%d: pattern %s without # boundary: annotation\n' \
                        "$file" "$((i + 1))" "'$pattern'"
                    violations=1
                fi
            fi
        done
    done

    # Check regex patterns with boundary lookback
    local all_regex=()
    all_regex+=("${BANNED_PROVIDER_TYPES_REGEX[@]}")
    all_regex+=("${BANNED_OTHER_REGEX[@]}")

    for pattern in "${all_regex[@]}"; do
        for ((i = 0; i < total_lines; i++)); do
            if [[ "${_BOUNDARY_LINES[$i]}" =~ $pattern ]]; then
                if ! has_boundary_annotation "$i"; then
                    printf 'BOUNDARY VIOLATION: %s:%d: pattern %s without # boundary: annotation\n' \
                        "$file" "$((i + 1))" "'$pattern'"
                    violations=1
                fi
            fi
        done
    done

    return $violations
}

# ── Mode functions ──

# Canonical mode: strict scan of tests/unit/
check_canonical() {
    local violations=0
    local scan_dir="tests/unit"

    local file
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        check_file_strict "$file" "CANONICAL" || violations=1
    done < <(get_scan_files "$scan_dir")

    return $violations
}

# Boundary mode: whitelist scan of integration/security/e2e/stress/batching
check_boundary() {
    local violations=0
    local scan_dirs=(
        "tests/integration"
        "tests/security"
        "tests/e2e"
        "tests/stress"
        "tests/batching"
    )

    local dir file
    for dir in "${scan_dirs[@]}"; do
        while IFS= read -r file; do
            [[ -z "$file" ]] && continue
            check_file_boundary "$file" || violations=1
        done < <(get_scan_files "$dir")
    done

    return $violations
}

# Root mode: strict scan of tests/*.py (root-level only)
check_root() {
    local violations=0
    local scan_dir="tests"

    local file
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        check_file_strict "$file" "ROOT" || violations=1
    done < <(get_root_files "$scan_dir")

    return $violations
}

# ── Main ──

main() {
    local mode="${1:-all}"
    local rc=0

    case "$mode" in
        canonical)
            check_canonical || rc=1
            ;;
        boundary)
            check_boundary || rc=1
            ;;
        root)
            check_root || rc=1
            ;;
        all)
            check_canonical || rc=1
            check_boundary || rc=1
            check_root || rc=1
            ;;
        *)
            echo "Usage: $0 [canonical|boundary|root|all]" >&2
            echo "  canonical — strict scan of tests/unit/" >&2
            echo "  boundary  — whitelist scan of tests/integration/, tests/security/, tests/e2e/, tests/stress/, tests/batching/" >&2
            echo "  root      — strict scan of tests/*.py (root-level only)" >&2
            echo "  all       — run canonical, boundary, and root (default)" >&2
            exit 1
            ;;
    esac

    if [[ $rc -eq 0 ]]; then
        echo ""
        echo "All test hardcode checks passed"
        echo ""
    fi

    exit $rc
}

main "$@"
