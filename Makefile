# Common tasks. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/sh
PYTHON ?= python3
OLLAMA_MODEL ?= $(shell grep -s '^OLLAMA_MODEL=' .env | cut -d= -f2)
OLLAMA_MODEL := $(or $(OLLAMA_MODEL),llama3.2:3b)

.PHONY: help install models lint test eval up down demo logs helm-lint tf-validate

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install Relay, the SDK and dev tools in the current virtualenv
	$(PYTHON) -m pip install -e ".[dev]" -e ./sdk

models: ## Install the spaCy models used by Presidio (~600 MB)
	$(PYTHON) -m pip install -r requirements-models.txt

lint: ## Ruff + mypy
	ruff check . && ruff format --check . && mypy

test: ## Fast test suite (Presidio detection replaced by a fake)
	pytest -q -m "not presidio"

eval: ## Masking evaluation with the real Presidio models (needs `make models`)
	pytest -q -m presidio && $(PYTHON) eval/masking/run_eval.py

up: ## Start the full stack and pull the local Ollama model
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example (change the passwords!)")
	docker compose up -d --build
	docker compose exec -T ollama ollama pull $(OLLAMA_MODEL)
	@echo "Waiting for Relay to load its models and become healthy..."
	@until curl -sf http://localhost:8000/healthz > /dev/null; do sleep 3; done
	@echo "Relay: http://localhost:8000   Grafana: http://localhost:3000 (admin / GRAFANA_ADMIN_PASSWORD)"

down: ## Stop the stack (add -v to `docker compose down` to also delete the data)
	docker compose down

demo: ## Send a prompt with PII and show masked prompt vs restored answer
	$(PYTHON) scripts/demo.py

logs: ## Follow Relay and collector logs (spans appear in the collector log)
	docker compose logs -f relay otel-collector

helm-lint: ## Validate the Helm chart
	helm lint deploy/helm/relay && helm template relay deploy/helm/relay > /dev/null

tf-validate: ## Validate the OCI Terraform (no cloud credentials needed)
	terraform -chdir=deploy/terraform fmt -check -recursive
	terraform -chdir=deploy/terraform init -backend=false -input=false
	terraform -chdir=deploy/terraform validate
