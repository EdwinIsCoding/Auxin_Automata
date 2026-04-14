.PHONY: bootstrap lint test demo clean

# ── Bootstrap ────────────────────────────────────────────────────────────────
# Install all workspace dependencies and pre-commit hooks.
# Prerequisites: uv, pnpm, cargo, solana-cli, anchor must already be installed.
bootstrap:
	cd sdk && uv sync
	cd twin && uv sync
	cd dashboard && pnpm install
	pre-commit install
	@echo "Bootstrap complete."

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	cd sdk && uv run ruff check . && uv run ruff format --check .
	cd twin && uv run ruff check . && uv run ruff format --check .
	cd dashboard && pnpm lint

# ── Test ─────────────────────────────────────────────────────────────────────
test:
	cd sdk && uv run pytest --cov=auxin_sdk --cov-fail-under=80
	cd twin && uv run pytest
	cd dashboard && pnpm test --if-present
	@# Anchor tests run only when programs/ workspace is initialised (Phase 2A)
	@[ -f programs/Anchor.toml ] && (cd programs && anchor test) || echo "Skipping anchor test (Phase 2A not yet started)"

# ── Demo ─────────────────────────────────────────────────────────────────────
# Spins up the full twin-mode stack via docker-compose.
# Added in Phase 4 (docker-compose.demo.yml does not exist yet).
demo:
	@[ -f docker-compose.demo.yml ] || (echo "docker-compose.demo.yml not yet created (Phase 4)" && exit 1)
	docker compose -f docker-compose.demo.yml up --build

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
