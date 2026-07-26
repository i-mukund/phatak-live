.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

dev-api: ## Run the backend with hot reload
	cd backend && uvicorn app.main:app --reload --port 8000

dev-web: ## Run the frontend with hot reload
	cd frontend && npm run dev

test: ## Run the backend test suite
	cd backend && pytest -q

cover: ## Run tests with a coverage report
	cd backend && pytest --cov=app --cov-report=term-missing --cov-report=html

lint: ## Lint and type-check everything
	cd backend && ruff check app tests && mypy app
	cd frontend && npm run lint && npm run typecheck

format: ## Auto-fix formatting
	cd backend && ruff check --fix app tests && ruff format app tests

load: ## Run the load profile against a local backend
	cd backend && locust -f tests/locustfile.py --host http://localhost:8000

up: ## Start the full production-shaped stack
	docker compose up --build

down: ## Stop the stack
	docker compose down

seed: ## Force an ingest tick against a running backend
	curl -sS -X POST -H "X-Admin-Key: $${ADMIN_API_KEY}" \
	  http://localhost:8000/api/v1/admin/ingest | python3 -m json.tool

.PHONY: help install dev-api dev-web test cover lint format load up down seed
