.PHONY: bootstrap setup lint test demo demo-down clean

# ── Bootstrap ────────────────────────────────────────────────────────────────
# Install all workspace dependencies and pre-commit hooks.
# Prerequisites: uv, pnpm, cargo, solana-cli, anchor must already be installed.
bootstrap:
	cd sdk && uv sync
	cd twin && uv sync
	cd dashboard && pnpm install
	pre-commit install
	@echo "Bootstrap complete."

# ── Devnet Setup ─────────────────────────────────────────────────────────────
# One-time setup: generates keypairs, airdrops SOL, initialises agent PDA.
# Safe to re-run — all steps are idempotent.
setup:
	cd sdk && uv run python ../scripts/setup_devnet.py

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	cd sdk && uv run ruff check . && uv run ruff format --check .
	cd twin && uv run ruff check . && uv run ruff format --check .
	cd dashboard && pnpm lint

# ── Test ─────────────────────────────────────────────────────────────────────
test:
	cd sdk && uv run python -m pytest --cov=src --cov-fail-under=80
	cd twin && uv run python -m pytest
	cd dashboard && pnpm test --if-present
	@# Anchor tests require a running solana-test-validator (start with: solana-test-validator --reset --quiet &)
	@[ -f programs/Anchor.toml ] && (cd programs && anchor test --skip-local-validator) || echo "Skipping anchor test (Anchor.toml not found)"

# ── Demo ─────────────────────────────────────────────────────────────────────
# Spins up the full twin-mode stack via docker-compose.
# Waits for services to be healthy, then prints all endpoint URLs.
demo:
	docker compose -f docker-compose.demo.yml up --build -d
	@echo ""
	@echo "Waiting for bridge to become healthy…"
	@for i in $$(seq 1 30); do \
		STATUS=$$(docker compose -f docker-compose.demo.yml ps --format json bridge 2>/dev/null \
		         | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('Health',''))" 2>/dev/null || echo ""); \
		[ "$$STATUS" = "healthy" ] && break; \
		sleep 2; \
	done
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Auxin Automata demo stack is up!"
	@echo ""
	@echo "  Dashboard   →  http://localhost:3000"
	@echo "  Grafana     →  http://localhost:3001"
	@echo "  Prometheus  →  http://localhost:9091"
	@echo "  Bridge /healthz → http://localhost:8767/healthz"
	@echo "  Bridge metrics  → http://localhost:9090/metrics"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

demo-down:
	docker compose -f docker-compose.demo.yml down --volumes

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
