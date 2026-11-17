.PHONY: help venv install migrate seed fetch-datasets sync-datasets validate content \
        backend frontend dev up down logs build-image loadtest notebook-venv local-notebooks \
        test test-backend test-frontend test-env test-security test-integration check clean

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip
NOTEBOOK_PY := .venv-notebook/bin/python
API := http://localhost:8000
WEB := http://localhost:5173
SERVING := $(abspath datasets/serving)

help:
	@echo "OpenCS Labs — common targets"
	@echo ""
	@echo "  make install          Create venv, install backend + frontend deps"
	@echo "  make fetch-datasets   Download, verify and manifest the dataset library"
	@echo "  make sync-datasets    Verify and upload datasets to MinIO"
	@echo "  make validate         Validate curriculum and exercise content"
	@echo "  make migrate          Apply database migrations"
	@echo "  make seed             Seed demo users, content and dataset catalogue"
	@echo "  make dev              Run backend (:8000) and frontend (:5173)"
	@echo "  make up               Build and run the full stack via docker compose"
	@echo "  make down             Stop the compose stack"
	@echo "  make test             Backend + frontend test suites"
	@echo "  make test-env         Notebook image environment smoke tests"
	@echo "  make build-image      Build the pinned analytics notebook image"
	@echo "  make notebook-venv    Create .venv-notebook from the analytics lock"
	@echo "  make local-notebooks  Run the local JupyterLab server (host processes)"
	@echo "  make loadtest         Staged load test against a running stack"
	@echo "  make check            Everything CI runs: lint, types, tests, content"

venv:
	@test -x $(PY) || python3 -m venv backend/.venv

install: venv
	$(PIP) install -q -r backend/requirements.txt
	cd frontend && npm install --include=dev

migrate:
	cd backend && .venv/bin/alembic upgrade head

seed:
	$(PY) scripts/seed.py

fetch-datasets:
	$(PY) scripts/fetch_datasets.py

sync-datasets:
	$(PY) scripts/sync_datasets.py

validate:
	$(PY) scripts/validate_content.py

content: validate

# Two terminals, or use `make up` for the containerised stack.
backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

# The dataset serving directory must be an absolute host path so the backend
# and the grading sandbox bind-mount the same bytes.
up:
	@DATASETS_SERVING_DIR=$(SERVING) docker compose up -d --build
	@echo "frontend: $(WEB)   api: $(API)/api/docs   hub: http://localhost:8001"

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

build-image:
	notebook-image/build.sh --no-test

# Host-process notebook environment: same pinned stack as the analytics image.
notebook-venv:
	@test -x $(NOTEBOOK_PY) || python3 -m venv .venv-notebook
	$(NOTEBOOK_PY) -m pip install -q -r notebook-image/requirements.lock

# Manual fallback; the backend normally auto-spawns this server on first use.
local-notebooks:
	$(NOTEBOOK_PY) -m jupyterlab --no-browser --ip=localhost --port=8888 \
		--ServerApp.root_dir=backend/data/local-notebooks \
		--ServerApp.token= --ServerApp.password=

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/pytest -q

test-frontend:
	cd frontend && npm run test -- --run

test-env: build-image
	docker run --rm \
		-v "$(SERVING):/opt/opencs/datasets:ro" \
		-v "$(abspath notebook-image/smoke-tests):/smoke:ro" \
		opencs/analytics:1.0.0 python -m pytest /smoke -q

test-security:
	cd backend && .venv/bin/pytest -q tests/test_security.py

test-integration:
	cd backend && .venv/bin/pytest -q -m integration

loadtest:
	$(PY) tests/load/run_loadtest.py --users 10 --duration 60

check: validate test-backend test-frontend
	cd frontend && ./node_modules/.bin/tsc --noEmit

clean:
	rm -rf backend/.pytest_cache frontend/dist frontend/node_modules/.vite
