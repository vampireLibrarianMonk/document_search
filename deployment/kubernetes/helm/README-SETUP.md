# Kubernetes (k3s + Helm) - Infrastructure Setup

How to build and stand up the k3s cluster with Helm from scratch.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| curl | any | Pre-installed on most systems |
| AWS credentials | - | `~/.aws/credentials` with Bedrock access |
| mkcert certs | - | Generated via `make certs` (for HTTPS) |

## Initial Setup

### 1. Install k3s

```bash
make k3s-install
```

This runs:
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--docker --disable traefik" sh -
```

Flags:
- `--docker`: uses your existing Docker runtime (no containerd)
- `--disable traefik`: we use nginx-ingress instead

### 2. Install socat (required for port-forwarding)

```bash
sudo apt install socat
```

### 3. Set up kubectl access

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes    # should show your machine as Ready
```

Add to your shell profile:
```bash
echo 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml' >> ~/.bashrc
```

### 4. Install Helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### 5. Build Docker images

```bash
docker build -t document-search-api:latest ./backend
docker build -t document-search-frontend:latest ./frontend
```

Since k3s uses the local Docker daemon (`--docker` flag), these images are immediately available to the cluster.

### 6. Deploy with Helm

```bash
make k3s-up
```

This runs:
```bash
helm upgrade --install document-search deployment/kubernetes/helm/document-search --namespace docsearch --create-namespace
```

### 7. Verify

```bash
make k3s-status
```

All pods should show `Running` within 30-60 seconds.

## HTTPS Setup

### 1. Generate certs (if not already done)

```bash
make certs
```

### 2. Create TLS secret

```bash
kubectl create secret tls docsearch-tls \
  --cert=deployment/docker/certs/local-dev.pem \
  --key=deployment/docker/certs/local-dev-key.pem \
  --namespace=docsearch
```

### 3. Install nginx ingress controller

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml
```

Wait for it:
```bash
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=90s
```

### 4. Upgrade the Helm release

```bash
make k3s-up
```

The ingress template automatically configures TLS with the `docsearch-tls` secret.

### 5. Verify HTTPS

```bash
curl -s https://app.localhost/       # should return 200
curl -s https://api.localhost/health  # should return {"status":"ok"}
```

## Helm Chart Structure

```
deployment/kubernetes/helm/document-search/
  Chart.yaml          # Chart metadata
  values.yaml         # All configurable values
  templates/
    namespace.yaml    # docsearch namespace
    api.yaml          # API deployment, service, PVC
    frontend.yaml     # Frontend deployment, service
    postgres.yaml     # Postgres deployment, service, PVC
    opensearch.yaml   # OpenSearch deployment, service, PVC
    bookstack.yaml    # BookStack + MySQL deployments, services, PVCs
    ingress.yaml      # Ingress with TLS
    rbac.yaml         # RBAC for Health tab (pod metrics access)
```

## Configuration

Edit `deployment/kubernetes/helm/document-search/values.yaml`:

```yaml
api:
  env:
    BEDROCK_MODEL_ID: anthropic.claude-3-haiku-20240307-v1:0    # change model
    AWS_REGION: us-east-1                                        # change region
  resources:
    limits:
      memory: 1Gi      # increase if needed
      cpu: "1"

postgres:
  storage: 5Gi         # increase for more documents

opensearch:
  storage: 10Gi        # increase for larger index
```

Apply changes:
```bash
make k3s-up
```

## Rebuilding After Code Changes

```bash
# Rebuild images
docker build -t document-search-api:latest ./backend
docker build -t document-search-frontend:latest ./frontend

# Restart pods to pick up new images
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl rollout restart deployment/api deployment/frontend -n docsearch
```

## Data Persistence

Data is stored in PersistentVolumeClaims:
- `postgres-data` (5Gi) - document metadata, chunks, usage tracking
- `opensearch-data` (10Gi) - search index
- `api-data` (2Gi) - uploaded files
- `bookstack-db-data` (2Gi) - wiki content

These survive pod restarts and Helm upgrades. To wipe:
```bash
make k3s-down
kubectl delete pvc --all -n docsearch
```

## Uninstall

```bash
# Remove the app
make k3s-down
kubectl delete namespace docsearch

# Remove nginx ingress
kubectl delete -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml

# Remove k3s entirely
sudo /usr/local/bin/k3s-uninstall.sh
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Pod in CrashLoopBackOff | `kubectl logs -n docsearch <pod-name>` to see error |
| API can't reach Postgres | Postgres pod may still be starting, wait 30s |
| Images not found | Rebuild with `docker build`, k3s uses local Docker images |
| Port-forward fails | Install socat: `sudo apt install socat` |
| Ingress not working | Check nginx controller is running: `kubectl get pods -n ingress-nginx` |
| HTTPS cert not trusted | Run `mkcert -install` and restart browser |
| Metrics not showing in Health tab | k3s includes metrics-server by default, wait 60s after boot |
