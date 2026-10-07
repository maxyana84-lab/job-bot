.PHONY: install lint test run up down logs

install:
	pip install -r requirements-dev.txt

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q

run:
	set -a && . ./.env && set +a && python -m app.main

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f job-bot
