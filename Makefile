.PHONY: help install install-dev validate-configs lint format typecheck security test test-unit ci compose-up compose-down clean seed-sample-data register-local-debezium

PYTHON := python3.11
VENV := .venv
VENV_BIN := $(VENV)/bin

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip setuptools wheel

install: $(VENV)/bin/activate  ## Install runtime deps
	$(VENV_BIN)/pip install -e .

install-dev: $(VENV)/bin/activate  ## Install dev deps
	$(VENV_BIN)/pip install -e ".[dev]"

validate-configs:  ## Validate MSK Connect configs
	$(VENV_BIN)/python scripts/validate_connect_configs.py mskconnect/

lint:  ## Run ruff
	$(VENV_BIN)/ruff check src tests scripts

format:  ## Auto-format
	$(VENV_BIN)/ruff format src tests scripts
	$(VENV_BIN)/ruff check --fix src tests scripts

typecheck:  ## Run mypy
	$(VENV_BIN)/mypy src --ignore-missing-imports

security:  ## Run bandit
	$(VENV_BIN)/bandit -c pyproject.toml -r src scripts -lll

test-unit:  ## Fast unit tests
	$(VENV_BIN)/pytest tests/unit -v -m unit

test: test-unit  ## Alias for test-unit

ci: lint typecheck security validate-configs test-unit  ## Full local CI

compose-up:  ## Start Kafka + Postgres + Debezium + sinks
	docker compose -f compose/docker-compose.yml up -d
	@sleep 10
	@echo "Stack started. Use 'make register-local-debezium' to register the CDC connector."

compose-down:  ## Stop stack (keeps data)
	docker compose -f compose/docker-compose.yml down

compose-clean:  ## Stop stack + remove all data
	docker compose -f compose/docker-compose.yml down -v

register-local-debezium:  ## Register Debezium Postgres connector against local stack
	bash scripts/register-local-debezium.sh

seed-sample-data:  ## Generate synthetic events to local Kafka
	$(VENV_BIN)/python scripts/seed_sample_data.py

demo-spark-job:  ## Run orders CDC enrichment against local stack
	$(VENV_BIN)/python -m streaming.jobs.orders_cdc_enrichment \
		--bootstrap-servers localhost:9092 \
		--checkpoint-location /tmp/checkpoints/orders \
		--product-dim-path /tmp/dims/products \
		--redis-host localhost \
		--redis-port 6379 \
		--opensearch-endpoint localhost \
		--iceberg-warehouse /tmp/iceberg-warehouse \
		--local

terraform-init-dev:
	cd infra/terraform && terraform init -backend-config=envs/dev.backend.hcl

terraform-plan-dev:
	cd infra/terraform && terraform plan -var-file=envs/dev.tfvars

terraform-apply-dev:
	cd infra/terraform && terraform apply -var-file=envs/dev.tfvars

clean:  ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info/
	rm -rf .pytest_cache/ .coverage htmlcov/
	rm -rf spark-warehouse/ metastore_db/ derby.log *.log
	rm -rf checkpoints/ flink-checkpoints/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

all: install-dev ci  ## Install + run full CI
