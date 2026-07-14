.PHONY: up up-detached down down-volumes logs ps test lint migrate backend-shell frontend-shell

up:
	docker compose up --build

up-detached:
	docker compose up --build -d

down:
	docker compose down

down-volumes:
	docker compose down -v

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	docker compose exec backend pytest

lint:
	docker compose exec backend ruff check .
	docker compose exec backend ruff format --check .
	docker compose exec backend mypy app
	docker compose exec frontend npm run lint
	docker compose exec frontend npm run type-check

migrate:
	docker compose exec backend alembic upgrade head

backend-shell:
	docker compose exec backend sh

frontend-shell:
	docker compose exec frontend sh
