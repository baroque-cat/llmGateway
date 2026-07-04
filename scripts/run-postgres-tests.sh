#!/usr/bin/env bash
# scripts/run-postgres-tests.sh
#
# Container lifecycle script for running @pytest.mark.postgres tests
# against a fresh test-database Docker service.
#
# Lifecycle: pre-teardown → up --wait → test groups → post-teardown
# Engine detection: podman-first, then docker. Exits 0 if neither found.

set -euo pipefail

# ── Color constants ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# ── Path resolution: SCRIPT_DIR → PROJECT_DIR (repo root) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# ── Engine detection (podman-first, then docker) ──
COMPOSE_CMD=()

if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    COMPOSE_CMD=(podman compose)
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
else
    printf '%b\n' "${YELLOW}No container engine (podman or docker) found. Skipping PostgreSQL tests.${NC}"
    exit 0
fi

# ── run_group function ──
# Runs a group of postgres-marked tests, handling exit codes:
#   - Exit 0: success (green message)
#   - Exit 5: no tests collected (yellow message, non-failure)
#   - Other non-zero: failure (red message, sets EXIT_CODE=1)
run_group() {
    local group_name="$1"
    local test_paths="$2"

    printf '%b\n' "${GREEN}=== Running ${group_name} tests ===${NC}"

    set +e
    # shellcheck disable=SC2086
    poetry run pytest $test_paths -v --timeout=60 --run-postgres -m "postgres"
    local rc=$?
    set -e

    if [[ $rc -eq 0 ]]; then
        printf '%b\n' "${GREEN}=== ${group_name} tests PASSED ===${NC}"
    elif [[ $rc -eq 5 ]]; then
        printf '%b\n' "${YELLOW}=== No postgres tests found for ${group_name} (exit 5) ===${NC}"
    else
        printf '%b\n' "${RED}=== ${group_name} tests FAILED (exit ${rc}) ===${NC}"
        EXIT_CODE=1
    fi
}

# ── Pre-teardown: remove any stale container from previous runs ──
"${COMPOSE_CMD[@]}" down -v 2>/dev/null || true

# ── Fresh start: start test-database container with healthcheck readiness ──
"${COMPOSE_CMD[@]}" up -d --wait test-database

# ── Run test groups ──
EXIT_CODE=0

run_group "schema" "tests/integration/db/"
run_group "repositories" "tests/integration/db/"
run_group "manager" "tests/integration/db/"
run_group "gatekeeper" "tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching"

# ── Post-teardown: always tear down (no error suppression) ──
"${COMPOSE_CMD[@]}" down -v

exit $EXIT_CODE
