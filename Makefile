.PHONY: lint typecheck test test-slow test-postgres test-all ci

# ── Lint ──
lint:
	poetry run ruff check src/ tests/

# ── Type check ──
typecheck:
	poetry run pyright

# ── Process-Isolation Test Groups ──
# Each group is a separate poetry run pytest invocation — fresh asyncio event loop.

# G1: Unit tests (core, db, metrics, providers, services) — excl. config
# G2: Unit/config tests (24 Pydantic-heavy files, fresh loop)
# G3: Integration + security + e2e
# G4: Batching tests
# G5: Root-level tests (module tests + future gatekeeper) — collected via inversion
# G6: Stress tests (slow, real HTTP/2) — only via make test-slow

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

# ── Stress tests (slow, real HTTP/2 server) ──
test-slow:
	@echo "=== G6: stress tests ==="
	poetry run pytest tests/stress/ -q --timeout=60 -m slow

# ── Postgres integration tests (require real DB) ──
test-postgres:
	poetry run pytest -v --run-postgres -m "postgres" || true

# ── Full suite ──
test-all: test test-slow
	@echo "==> All tests complete"

# ── CI pipeline ──
ci: lint typecheck test
