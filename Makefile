.PHONY: install infra migrate api web worker test check build
install:
	uv sync --locked
	npm ci --prefix apps/web
infra:
	docker compose -f infra/compose.yaml up -d postgres egress
migrate:
	uv run alembic upgrade head
api:
	uv run uvicorn apps.api.main:app_factory --factory --host 127.0.0.1 --port 8110
web:
	NEXUS_API_URL=http://127.0.0.1:8110 npm run dev --prefix apps/web -- --port 3101
worker:
	uv run python -m nexus.workers.runtime
test:
	uv run pytest -q
	npm run test --prefix apps/web
check:
	uv run ruff check .
	npm run typecheck --prefix apps/web
build:
	npm run build --prefix apps/web
