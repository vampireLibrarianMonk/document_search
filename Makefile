COMPOSE := docker compose -f deployment/docker/docker-compose.yml

.PHONY: dev-backend dev-frontend dev-all up down logs ps build up-https certs

# ── Stage 1: Local dev ──────────────────────────────────────
dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

dev-all:
	$(MAKE) dev-backend & $(MAKE) dev-frontend & wait

# ── Stage 2: Docker Compose ─────────────────────────────────
up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) --profile https down

logs:
	$(COMPOSE) --profile https logs -f

ps:
	$(COMPOSE) --profile https ps

build:
	$(COMPOSE) build

# ── Stage 3: HTTPS ──────────────────────────────────────────
certs:
	./deployment/docker/certs/generate.sh

up-https:
	$(COMPOSE) --profile https up --build -d

# ── Testing ─────────────────────────────────────────────────
test:
	cd backend && python -m pytest tests/ -v --ignore=tests/test_integration.py

test-integration:
	cd backend && python -m pytest tests/test_integration.py -v

test-all:
	cd backend && python -m pytest tests/ -v

test-coverage:
	cd backend && python -m pytest tests/ -v --cov=app --cov-report=term-missing

# ── Kubernetes (k3s + Helm) ─────────────────────────────────
k3s-install:
	curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--docker --disable traefik" sh -

k3s-up:
	helm upgrade --install document-search deployment/kubernetes/helm/document-search --namespace docsearch --create-namespace

k3s-down:
	helm uninstall document-search --namespace docsearch

k3s-status:
	kubectl get pods -n docsearch -o wide
