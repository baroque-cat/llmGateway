.PHONY: lint typecheck test test-slow test-postgres test-all ci test-gatekeeper test-boundary

# ── Lint ──
lint:
	poetry run ruff check src/ tests/

# ── Type check ──
typecheck:
	poetry run pyright

# ── Process-Isolation Test Groups ──
# Each group is a separate poetry run pytest invocation — fresh asyncio event loop.
#
# G1: Unit tests (core, db, metrics, providers, services) — excl. config
# G2: Unit/config tests (24 Pydantic-heavy files, fresh loop)
# G3: Integration + security + e2e
# G4: Batching tests
# G5: Root-level tests (gatekeeper + structural) — collected via inversion
# G6: Stress tests (real HTTP/2) — split into 3 sub-groups by duration
#     G6a: Fast server + metrics tests (<10s each)
#     G6b: Concurrency scenarios (10-15s each)
#     G6c: Long-running scenarios (30-35s each)

test:
	@echo "=== G1: unit tests (core, db, metrics, providers, services) ==="
	poetry run pytest tests/unit/ --ignore=tests/unit/config -q --timeout=30 -m "not slow and not postgres"
	@echo "=== G2: unit/config tests ==="
	-poetry run pytest tests/unit/config/ -q --timeout=30 -m "not slow and not postgres"
	@echo "=== G3: integration + security + e2e ==="
	-poetry run pytest tests/integration/ tests/security/ tests/e2e/ -q --timeout=30 -m "not slow and not postgres"
	@echo "=== G4: batching ==="
	-poetry run pytest tests/batching/ -q --timeout=30 -m "not slow and not postgres"
	@echo "=== G5: root-level tests (gatekeeper) ==="
	-poetry run pytest tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching -q --timeout=30 -m "not slow and not postgres"

# ── Standalone gatekeeper target (G5 only, root-level tests) ──
test-gatekeeper:
	poetry run pytest tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/security --ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching -q --timeout=30 -m "not slow and not postgres"

# ── Standalone boundary compliance check (single file, fast) ──
test-boundary:
	poetry run pytest tests/test_boundary_compliance.py -q --timeout=30

# ── Stress tests (slow, real HTTP/2 server) ──
# Isolated into 3 sub-groups by per-test duration to prevent timeout cascades:
#   G6a: ephemeral server + metrics (all <10 s per test)
#   G6b: concurrency / freeze / saturation (10–15 s per test)
#   G6c: long-running production scenarios (30–35 s per test)
# All groups are fault-tolerant (-prefix) — one group failing does not stop the rest.
test-slow:
	@echo "=== G6a: fast server + metrics tests ==="
	-poetry run pytest tests/stress/test_ephemeral_server.py tests/stress/test_metrics_collector.py -q --timeout=15 -m slow
	@echo "=== G6b: concurrency scenarios ==="
	-poetry run pytest tests/stress/test_cap_prevents_freeze.py tests/stress/test_connection_growth.py tests/stress/test_multi_client.py tests/stress/test_stream_exhaustion.py tests/stress/test_cascading_freeze.py tests/stress/test_pool_saturation.py tests/stress/test_throughput_bottleneck.py -q --timeout=30 -m slow
	@echo "=== G6c: long-running scenarios ==="
	-poetry run pytest tests/stress/test_pool_recovery.py tests/stress/test_production_load.py -q --timeout=60 -m slow

# ── Postgres integration tests (require Docker/Podman) ──
# Uses test-database container on port 5433.  Gracefully skips if no container
# engine is available (script exits 0).
test-postgres:
	bash scripts/run-postgres-tests.sh

# ── Full suite (G1–G6 + Postgres when Docker is available) ──
# Runs all test groups.  Postgres tests are conditional: run only if Docker or
# Podman is available, otherwise print a notice and skip.
test-all: test test-slow
	@if command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1; then \
		$(MAKE) test-postgres; \
	else \
		echo "==> Skipping postgres tests: no Docker/Podman found"; \
	fi
	@echo "==> All tests complete"

# ── CI pipeline (lint + typecheck + test, no stress, no postgres) ──
ci: lint typecheck test

# ── Help ──
help:
	@echo "Usage:"
	@echo "  make test          — G1–G5 (~3 s)"
	@echo "  make test-slow     — G6 stress tests (~60 s)"
	@echo "  make test-postgres — PostgreSQL integration tests (requires Docker)"
	@echo "  make test-all      — G1–G6 + Postgres (~65 s without DB)"
	@echo "  make ci            — lint + typecheck + G1–G5 (~10 s)"
	@echo "  make lint          — ruff check"
	@echo "  make typecheck     — pyright"
