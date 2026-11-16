# JupyterHub control plane

JupyterHub is the notebook control plane: it authenticates the student, spawns
one single-user server per student, proxies their traffic and culls idle
servers. The FastAPI backend is a Hub *service* (it holds a Hub API token); the
browser never receives one.

```
browser → POST /api/v1/auth/login → backend issues JWT (HttpOnly cookie)
browser → GET /hub/login            → opencs_auth.py verifies the JWT
                                    → KubeSpawner/DockerSpawner starts the pod
                                    → proxy routes /user/<name>/ to it
```

## Files

| File | Purpose |
|---|---|
| `jupyterhub_config.py` | Hub, proxy, spawner, storage, idle culling, services and roles |
| `opencs_auth.py` | `OpenCSAuthenticator`: verifies the backend's session JWT |
| `Dockerfile` | JupyterHub + KubeSpawner + DockerSpawner + idle-culler + PyJWT |

## Two spawners, one contract

| `OPENCE_SPAWNER` | Used by | Isolation |
|---|---|---|
| `kubernetes` (default) | production | one pod per student, PVC home, read-only dataset PVC, capabilities dropped, no service-account token |
| `docker` | single-host Compose | one container per student, dataset tree bind-mounted read-only |

The authenticated identity is the same in both: the `hub` claim of the JWT.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `OPENCE_JWT_SECRET` | — | Shared HS256 key with the backend. **Required.** |
| `OPENCE_JWT_ISSUER` | `opencs` | Expected `iss` claim |
| `OPENCE_SESSION_COOKIE` | `opencs_session` | Cookie carrying the JWT |
| `OPENCE_PUBLIC_ORIGIN` | `http://localhost:5173` | Frontend, used for login redirects |
| `OPENCE_JUPYTERHUB_API_TOKEN` | — | Token the backend uses. **Required.** |
| `OPENCE_SPAWNER` | `kubernetes` | `kubernetes` or `docker` |
| `OPENCE_NOTEBOOK_IMAGE` | `opencs/analytics:1.0.0` | Single-user image |
| `OPENCE_DATASET_MOUNT_PATH` | `/opt/opencs/datasets` | Where datasets appear in a pod |
| `OPENCE_DATASET_SERVING_DIR` | — | Host path, bind-mounted in Docker mode |
| `OPENCE_POD_MEMORY` / `OPENCE_POD_CPU` | `2Gi` / `1` | Per-student limits |
| `OPENCE_POD_STORAGE` | `5Gi` | Per-student PVC |
| `OPENCE_IDLE_TIMEOUT_SECONDS` | `1800` | Cull after this much inactivity |
| `JUPYTERHUB_CRYPT_KEY` | — | Fernet key; without it `auth_state` is not persisted |

## Security notes

- The JWT is **verified, never minted** here. The signing key is shared with
  the backend, which is the only issuer.
- Only `HS256` is accepted: it avoids `alg=none` and algorithm-confusion bugs.
- `?next=` is validated by `safe_next_url` (absolute paths only), so login
  cannot be used as an open redirect.
- The notebook server runs with an empty token/password **because** the Hub
  authenticates in front of it. That is only safe if `/user/<name>/` is reachable
  exclusively through the Hub proxy — one ingress origin, never a direct pod
  route.
- Logging out of the notebook does not sign the student out of the course app:
  the OpenCS session cookie belongs to the backend and is left alone.

## Run

```bash
# Compose stack (DockerSpawner):
make up

# Validate the config without starting the Hub:
docker run --rm -e OPENCE_JWT_SECRET=x -e OPENCE_JUPYTERHUB_API_TOKEN=y \
  opencs/jupyterhub:1.0.0 jupyterhub -f /srv/jupyterhub/jupyterhub_config.py --show-config
```

## Production

KubeSpawner is the production path; see `infrastructure/` and
`docs/ADR/001-jupyterhub-kubernetes.md`.
