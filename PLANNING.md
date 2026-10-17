# devops-health-check — Architecture Spec & Acceptance Criteria

Portfolio-first DevOps project: a minimal Flask health service, containerized, CI-tested,
and deployed to local Kubernetes (Minikube). No cloud, no secrets, no databases, no GitOps.

## A. Architecture overview

- **App**: single-file Flask service `app.py` using the app-factory pattern (`create_app`).
  Two endpoints: `GET /health` (liveness) and `GET /ready` (readiness).
  Served by a pinned WSGI server (`gunicorn`) bound to `0.0.0.0:8000`.
- **Liveness vs readiness**: `/health` proves the *process* is up — it returns 200 whenever
  the service can respond, with identity/version/timestamp. `/ready` proves the service can
  *accept traffic* — it depends on a config condition (env `APP_READY`, see §C) and returns
  503 while not ready. This is what lets k8s gate traffic and drain the pod cleanly.
- **Container**: reproducible `python:3.12-slim` image, non-root user, minimal layers,
  `EXPOSE 8000`, stable versioned tag `devops-health-check:0.1.0` (never `latest`).
- **CI**: GitHub Actions runs pytest and builds the Docker image on push + PR, and
  validates k8s YAML. CI only *builds/validates* the image — it does not deploy anywhere.
- **Kubernetes**: `k8s/` manifests deploy into namespace `devops-health` — 2-replica
  Deployment (liveness→`/health`, readiness→`/ready`, non-root, resources), a ClusterIP
  Service (80→8000), and a non-sensitive ConfigMap. The image is built locally for
  Minikube's docker driver (`minikube image build`), so no registry is involved.

## B. Exact file tree to create

```
devops-health-check/
├── app.py                          # Flask factory + /health + /ready
├── tests/
│   └── test_app.py                # pytest suite (use app.test_client())
├── requirements.txt               # pinned: flask, gunicorn, pytest
├── Dockerfile                     # python:3.12-slim, non-root, EXPOSE 8000
├── .dockerignore
├── .gitignore
├── README.md
├── .github/
│   └── workflows/
│       └── ci.yml                 # pytest + docker build + k8s YAML validate
└── k8s/
    ├── namespace.yaml             # devops-health
    ├── configmap.yaml             # APP_NAME / APP_ENV / APP_PORT / APP_READY
    ├── deployment.yaml            # 2 replicas, probes, non-root, resources
    └── service.yaml               # ClusterIP 80 -> 8000
```

### Pinned `requirements.txt` (verify latest-stable at implementation time; pin exact)
```
flask==3.0.3
gunicorn==22.0.0
pytest==8.2.2
```

## C. Readiness-logic design decision

- `/health` (liveness): unconditional on env. Returns `200` JSON
  `{"service": <APP_NAME>, "version": "0.1.0", "status": "healthy", "timestamp": <iso>}`.
- `/ready` (readiness): reads env `APP_READY` (default `"true"`, case-insensitive).
  - `APP_READY in {"true","1","yes"}` → `200` `{"ready": true}`.
  - otherwise → `503` `{"ready": false, "reason": "APP_READY is not enabled"}`.
- **Why this is meaningful, not a duplicate of /health**: it is a *gateable dependency
  condition*, not process liveness. In k8s the ConfigMap sets `APP_READY: "true"` so pods
  pass readiness; flipping it to `"false"` makes the readinessProbe fail and k8s stop
  routing traffic while liveness still passes — the exact semantics of a draining/unready
  but alive service. Tests set the env var per-case to exercise both branches.
- **404/405 behaviour**: unknown path → `404`; disallowed method on an existing route
  (e.g. `POST /health`) → `405`. Flask provides both natively; assert them in tests.

## D. Acceptance criteria (numbered, testable)

**App behaviour**
1. `GET /health` → 200, JSON with `service`, `version`, `status: "healthy"`, `timestamp`.
2. `GET /ready` with `APP_READY` unset or `"true"` → 200, JSON `ready: true`.
3. `GET /ready` with `APP_READY="false"` → 503, JSON `ready: false` + `reason`.
4. `GET /nope` (unknown path) → 404.
5. `POST /health` → 405.

**Tests**
6. `python -m pytest -v` exits 0 with a suite covering AC-1…AC-5 (≥5 test cases).
7. Failure cases (AC-3, AC-4, AC-5) are asserted explicitly, not just success paths.

**Dockerfile / image security**
8. Base image pinned to `python:3.12-slim` (exact tag, no `:latest` / floating tag).
9. Image runs as a non-root user (`USER appuser`, UID/GID 1000);
   `docker run --rm <img> id` → `uid=1000(appuser)`.
10. `EXPOSE 8000`; server binds `0.0.0.0:8000`; `pip install` uses `--no-cache-dir`.
11. `docker build -t devops-health-check:0.1.0 .` exits 0; running the image and
    `curl /health` returns 200.

**CI (`.github/workflows/ci.yml`)**
12. Triggers on `push` (main) and `pull_request`.
13. Steps: setup Python 3.12 → `pip install -r requirements.txt` → `pytest -v` →
    `docker build -t devops-health-check:0.1.0` → validate `k8s/*.yaml`.
14. k8s YAML validated by kubeconform (single-binary download) with a
    `python -c "import yaml; ...safe_load_all..."` fallback.
15. No secrets, no registry login/push, no cloud cluster — build + validate only.

**Kubernetes manifests**
16. `deployment.yaml`: `replicas: 2`, `image: devops-health-check:0.1.0` (pinned),
    `imagePullPolicy: IfNotPresent`, `containerPort: 8000`, `securityContext`
    `runAsNonRoot: true` + `runAsUser: 1000`, `resources` requests+limits,
    `livenessProbe` httpGet `/health:8000`, `readinessProbe` httpGet `/ready:8000`,
    labels consistent with its `selector`.
17. `service.yaml`: type `ClusterIP`, `port: 80` → `targetPort: 8000`, selector matches
    the Deployment labels.
18. `configmap.yaml`: `APP_NAME`, `APP_ENV`, `APP_PORT`, `APP_READY` only; no Secret
    resource anywhere in the repo.
19. `namespace.yaml` creates `devops-health`; all k8s kubectl commands in the README use
    `-n devops-health`.
20. Every `k8s/*.yaml` parses as valid YAML (AC-13/AC-14 tooling passes).

**README completeness**
21. Prerequisites: Python 3.12, Docker, kubectl, Minikube, GitHub.
22. Local run: venv + `pip install -r requirements.txt` + start gunicorn on :8000.
23. Docker: `docker build` + `docker run -p 8000:8000 devops-health-check:0.1.0`.
24. Tests: `python -m pytest -v` (also mirrors CI).
25. CI explainer: what the workflow does; explicitly says CI *builds* the image and does
    **not** deploy to any cluster.
26. K8s section: `minikube image build -t devops-health-check:0.1.0 -f Dockerfile .`,
    `kubectl apply -f k8s/`, inspect (`kubectl get deploy/svc/pods -n devops-health`),
    `kubectl logs`, test via `kubectl port-forward`, `kubectl scale`, and cleanup
    (`kubectl delete -f k8s/`, `minikube image rm`).

**Git hygiene**
27. `.gitignore`: `__pycache__/`, `*.pyc`, `.pytest_cache/`, venv, `.env`, `.DS_Store`.
28. `.dockerignore`: `.git`, `.github`, `tests/`, caches, venv, k8s, docs — keeps image
    build context small and secrets out.
29. No secrets/credentials committed; dependencies pinned; single clean `main` history.

## E. Open questions / assumptions

- **WSGI server**: chose `gunicorn` (portfolio-recognisable). `waitress` is an
  acceptable alternative (pure-Python, no build step on slim). Confirm one before coding.
- **Namespace**: include `k8s/namespace.yaml` + `devops-health` for isolation/portfolio
  quality; the alternative (default ns) is also valid — picking the namespace file.
- **`requirements.txt` scope**: single file with runtime+test deps per the brief
  (so CI and the image share it). Hardening option: split `requirements-dev.txt` to keep
  pytest out of the image — noted, not required.
- **Pinned versions** (AC list in §B): use the exact pins above but confirm they are the
  latest stable releases at implementation time and pin those instead.
- **YAML validation**: prefer kubeconform; if binary download is flaky in CI, the
  python-`yaml` fallback (AC-14) is acceptable.
- **Assumption**: Minikube `docker` driver shares the host Docker daemon, so
  `minikube image build` (which wraps `docker build`) puts the image where the cluster's
  containerd runtime can use it — hence `imagePullPolicy: IfNotPresent` and no registry.
- **Assumption**: orchestrator creates/pushes the GitHub repo; this repo's CI is defined
  here but only takes effect once `yashmahajan11234567/devops-health-check` exists.
