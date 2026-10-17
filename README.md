# devops-health-check

A minimal, production-shaped Flask health service — containerized, CI-tested, and ready
to deploy to local Kubernetes (Minikube). Built as a portfolio piece to demonstrate the
DevOps fundamentals: **liveness vs readiness probes, non-root containers, pinned
dependencies, and a CI pipeline that builds and validates but never deploys.**

No cloud, no databases, no secrets, no registries.

## What it does

| Endpoint    | Kind      | Behaviour                                                                                                            |
| ----------- | --------- | -------------------------------------------------------------------------------------------------------------------- |
| `GET /health` | liveness  | Always `200` while the process is alive. Returns `{service, version, status, timestamp}`. Proves the *process* is up. |
| `GET /ready`  | readiness | `200 {"ready": true}` when the service can accept traffic; `503 {"ready": false, "reason": ...}` otherwise.            |

Readiness is gated on the env var `APP_READY` (values `true`/`1`/`yes`, case-insensitive;
**default is ready when unset**). This is the point of the project: in Kubernetes, the
ConfigMap sets `APP_READY: "true"` so pods receive traffic — flipping it to `"false"`
fails the readiness probe, so Kubernetes stops routing traffic **while liveness still
passes**. That is exactly the semantics of a draining-but-alive service.

Unknown paths return `404`; disallowed methods (e.g. `POST /health`) return `405`.

## Prerequisites

- **Python 3.12** (local run + tests)
- **Docker** (image build/run)
- **kubectl** (Kubernetes CLI)
- **Minikube** (local cluster, docker driver)
- **GitHub** account (the CI workflow activates once the repo is pushed)

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# serve with gunicorn on :8000 (mirrors the container)
gunicorn --bind=0.0.0.0:8000 --workers=2 app:app
```

Exercise both endpoints:

```bash
curl -s http://localhost:8000/health   # -> 200 {"status": "healthy", ...}
curl -s http://localhost:8000/ready    # -> 200 {"ready": true}

# simulate a not-ready service, then re-check
APP_READY=false gunicorn --bind=0.0.0.0:8000 --workers=2 app:app
curl -si http://localhost:8000/ready   # -> 503 {"ready": false, "reason": "APP_READY is not enabled"}
curl -s  http://localhost:8000/health  # -> still 200 (liveness is independent)
```

## Run the tests

```bash
python -m pytest -v
```

The suite covers success **and** failure cases: `200 /health`, `200 /ready` (default and
truthy values), `503 /ready` with a reason, `404` unknown path, `405` wrong method.

## Docker

```bash
docker build -t devops-health-check:0.1.0 .
docker run --rm -p 8000:8000 devops-health-check:0.1.0
curl -s http://localhost:8000/health
```

The image is deliberately secure-by-default:

- base pinned to `python:3.12-slim` (never a floating tag),
- runs as non-root `appuser` (UID/GID 1000) with a `USER` directive,
- `pip install --no-cache-dir`, minimal layers (deps layer cached separately from code),
- `EXPOSE 8000`, gunicorn bound to `0.0.0.0:8000`,
- `.dockerignore` keeps tests, manifests, docs, and any local secrets out of the build context.

Verify it truly runs as non-root:

```bash
docker run --rm devops-health-check:0.1.0 id
# -> uid=1000(appuser) gid=1000(appuser)
```

## CI (GitHub Actions)

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:

1. **Set up Python 3.12** and `pip install -r requirements.txt` (pinned deps).
2. **`pytest -v`** — the app's behaviour is the contract.
3. **`docker build -t devops-health-check:0.1.0 .`** — proves the image builds.
4. **Validate `k8s/*.yaml` with kubeconform** (single static binary) — catches invalid
   Kubernetes manifests before anyone applies them. If the binary download ever fails,
   a fallback step parses every manifest with `python -c "import yaml; ...safe_load_all..."`
   so CI still verifies the YAML rather than hard-failing on a tooling hiccup.

> **CI builds the image and validates manifests — it does not deploy anywhere.**
> There is no registry login/push, no cluster credentials, no secrets in the workflow.
> Deployment to Kubernetes is an explicit, manual step (below). Build ≠ deploy is the
> intentional separation: the pipeline proves the artifact is good; a human (or a later
> CD stage) decides when and where it runs.

## Deploy to Minikube

The cluster uses Minikube's **docker driver**, so the image must be built into the
Docker daemon Minikube uses — not pushed to a registry. Use `minikube image build`
(**not** plain `docker build`; the cluster's containerd runtime can't see images built
outside it):

```bash
# 1. start the cluster (docker driver)
minikube start --driver=docker

# 2. build the image into Minikube's docker daemon
minikube image build -t devops-health-check:0.1.0 -f Dockerfile .

# 3. apply the manifests — namespace file first on a fresh cluster,
#    otherwise non-namespaced resources can race ahead of the namespace
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/ -n devops-health

# 4. inspect
kubectl get deploy,svc,pods -n devops-health
kubectl logs -n devops-health deploy/devops-health-check --tail=20
```

Test the service through the cluster:

```bash
# port-forward the Service (80 -> 8000 happens inside the cluster)
kubectl port-forward -n devops-health svc/devops-health-check 8080:80
curl -s http://localhost:8080/health
curl -s http://localhost:8080/ready
# Ctrl-C to stop the forward when done
```

Watch readiness gating in action:

```bash
# flip the ConfigMap and restart pods so they re-read env
kubectl set env -n devops-health deploy/devops-health-check APP_READY=false
kubectl rollout restart -n devops-health deploy/devops-health-check
kubectl get pods -n devops-health          # pods report Running but NOT Ready (1/2, 2/2...)
kubectl scale -n devops-health deploy/devops-health-check --replicas=3
# liveness keeps passing the whole time — the service is alive, just not receiving traffic

# restore
kubectl set env -n devops-health deploy/devops-health-check APP_READY=true
kubectl rollout restart -n devops-health deploy/devops-health-check
```

Clean up:

```bash
kubectl delete -f k8s/ -n devops-health
minikube image rm devops-health-check:0.1.0
minikube stop   # optional; or minikube delete to remove the cluster entirely
```

All `kubectl` commands target `-n devops-health` — the namespace created by
`k8s/namespace.yaml`, keeping the deployment isolated from anything else in the cluster.

## Project layout

```
devops-health-check/
├── app.py                  # Flask factory + GET /health (liveness) + GET /ready (readiness)
├── tests/
│   └── test_app.py         # pytest: 200/503/404/405 cases, APP_READY branches
├── requirements.txt        # pinned: flask, gunicorn, pytest
├── Dockerfile              # python:3.12-slim, non-root, EXPOSE 8000
├── .dockerignore           # small build context; no tests/k8s/docs/secrets in the image
├── .gitignore              # venvs, caches, .env, logs
├── .github/workflows/ci.yml # pytest + docker build + kubeconform (yaml fallback)
└── k8s/
    ├── namespace.yaml      # devops-health
    ├── configmap.yaml      # APP_NAME / APP_ENV / APP_PORT / APP_READY (no secrets)
    ├── deployment.yaml     # 2 replicas, probes, non-root, resources
    └── service.yaml        # ClusterIP 80 -> 8000
```
