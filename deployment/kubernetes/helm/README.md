# Kubernetes (k3s + Helm) - User Operations

Once the cluster is running, here's how to use it.

## URLs

| Service   | URL                         |
| --------- | --------------------------- |
| App       | https://app.localhost       |
| API Docs  | https://api.localhost/docs  |
| BookStack | https://bookstack.localhost |

If ingress isn't set up, use port-forwarding:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl port-forward -n docsearch svc/frontend 5173:80 &
kubectl port-forward -n docsearch svc/api 8000:8000 &
kubectl port-forward -n docsearch svc/bookstack 6875:80 &
```

Then access at `http://localhost:5173`, `http://localhost:8000/docs`, `http://localhost:6875`.

## Commands

```bash
make k3s-up        # Deploy or upgrade the release
make k3s-down      # Remove the release
make k3s-status    # Show pod status
```

## Health Tab

Click "🏥 Health" in the app to see:

- Pod count (running/pending/failed)
- Per-pod status with component name, age, restarts, CPU/memory
- Color-coded: green = healthy, red = failing

## Uploading, Searching, Asking, Creating, Gap-to-Email

Same as Docker Compose. See the main app README for full usage instructions.

## Scaling

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl scale deployment/api -n docsearch --replicas=2
```

## Viewing Logs

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl logs -n docsearch -l component=api -f          # API logs
kubectl logs -n docsearch -l component=opensearch -f   # OpenSearch logs
```

## Restarting a Service

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl rollout restart deployment/api -n docsearch
```

## Configuration Changes

Edit `deployment/kubernetes/helm/document-search/values.yaml`, then:

```bash
make k3s-up    # Helm upgrade applies changes
```

## BookStack Setup

BookStack runs as a pod in the cluster. To set it up:

### 1. Port-forward to access BookStack

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl port-forward -n docsearch svc/bookstack 6875:80 &
```

### 2. Log in and create an API token

1. Open http://localhost:6875
2. Log in with `admin@admin.com` / `password`
3. Click your avatar (top right) > "Edit Profile"
4. Scroll to "API Tokens" > "Create Token"
5. Copy the Token ID and Token Secret

### 3. Configure the app

Either update `values.yaml`:

```yaml
api:
  env:
    BOOKSTACK_TOKEN_ID: "your-token-id"
    BOOKSTACK_TOKEN_SECRET: "your-token-secret" # pragma: allowlist secret
```

Then `make k3s-up`.

Or set it at runtime through the app's Settings > Configuration panel (no redeploy needed).
