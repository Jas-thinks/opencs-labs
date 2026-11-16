# Implementation-level technical decisions

This file records decisions that are narrower than the architectural ADRs in
`docs/ADR/` but still constrain how the code is written.

## Grading runs in a container, never in-process

**Decision.** Student code is executed only inside a short-lived sandbox built
from the same pinned analytics image used for notebooks
(`opencs/analytics:1.0.0`). There are two interchangeable strategies behind one
`Sandbox` protocol:

- **`docker`** — development and the single-host Compose stack. `docker run`
  with `--network none`, memory/CPU caps, `--pids-limit 256`,
  `--cap-drop ALL`, `--security-opt no-new-privileges`, a `noexec,nosuid`
  tmpfs `/tmp`, the dataset tree read-only, and a per-run staging directory.
- **`kubernetes`** — production. A `batch/v1` Job in the `opencs-grading`
  namespace: no service-account token, `runAsNonRoot` uid 1000, read-only root
  filesystem, all capabilities dropped, `RuntimeDefault` seccomp, resource
  limits, `backoffLimit: 0`, `ttlSecondsAfterFinished: 300`. Network isolation
  comes from the namespace's `default-deny-all` policy whose only allowed
  egress is DNS.

Both produce the same single `###OPENCE_RESULT###` line, so parsing and scoring
are shared. The execution strategy is selected by `OPENCE_GRADER`.

**Why.** It satisfies HLD rule 7 ("never execute student code in the FastAPI
process") and gives a clean, disposable filesystem per attempt.

**Production constraint.** A hardened backend pod has a read-only root
filesystem and no Docker socket, so `OPENCE_GRADER=docker` cannot work there.
Startup validation rejects that combination in production rather than leaving a
setting that fails on first use. The `opencs-grading` namespace is also
separate from `opencs` and `opencs-hub`, so a policy mistake cannot expose the
platform database or notebook plane to graded code.

**Consequence.** If the sandbox is unavailable the evaluate endpoint returns
`503 UPSTREAM_UNAVAILABLE` — it never pretends an evaluation happened. A
sandbox that prints no result marker is scored as a failure, not a pass.

## jupyterhub-singleuser, not plain JupyterLab, in both images

**Decision.** The notebook image ships the `jupyterhub` package, and both the
DockerSpawner and KubeSpawner start single-user servers with
`jupyterhub-singleuser`, not `jupyter lab`.

**Why.** JupyterHub proxies `/user/<name>/` to the server and authenticates the
short-lived token it minted for the user. Only `jupyterhub-singleuser` speaks
that contract (validating the token, honouring `JUPYTERHUB_SERVICE_PREFIX`,
serving the contents API). A plain `jupyter lab` serves no single-user API, so
every backend contents request returned 403/500. A smoke test
(`test_jupyterhub_singleuser_entrypoint_is_present`) now pins this.

## Contents calls use the proxy, not the Hub API

**Decision.** `/user/<name>/...` requests go to the Hub **proxy**
(`OPENCE_JUPYTERHUB_PROXY_URL`, port 8000), while `/hub/api/...` goes to the Hub
**API** (`OPENCE_JUPYTERHUB_API_URL`, port 8081).

**Why.** They are different listeners. The API answers 500 for `/user/...`
paths; only the proxy routes them to the single-user server. Pointing both at
one URL made well-formed requests look like authorisation failures.

**Consequence.** These are separate settings because they are separate things.
They default to the same host, so a single-origin deployment sets neither.

## Token-authenticated writes carry no XSRF header

**Decision.** The backend sends `Authorization: token <minted>` and does **not**
send `X-XSRFToken` on contents writes.

**Why.** A request authenticated with a Hub-minted token is exempt from the
single-user server's XSRF check. Sending a *mismatched* header is worse than
sending none: it fails with "XSRF cookie does not match PUT argument". The
earlier attempts (arbitrary value, then a seeded cookie) both broke writes this
way.

## Staging directories must be host-visible for the Docker sandbox

**Decision.** `OPENCE_GRADER_STAGING_DIR` is bind-mounted into the backend
container at the same absolute path, and each evaluation stages its files in a
fresh subdirectory there.

**Why.** When the backend runs in a container and starts sibling containers
through the host daemon, the daemon resolves a bind-mount source on the
**host**. A `TemporaryDirectory` inside the backend container therefore mounts
an empty directory, and the sandbox reports "notebook.json is missing". Left
empty, the setting falls back to a plain temp directory, which is correct when
the backend runs on the host.

## DockerSpawner needs a per-user volume, not just `remove = True`

**Decision.** `remove = True` (delete the container on stop) is paired with a
named volume `jupyter-{username}` mounted at `/home/opencs`.

**Why.** Without the volume, removing the container also removes the student's
notebooks — the opposite of persistence. A `pre_spawn_hook` chowns the volume to
1000:1000 through the Docker client, because a freshly created volume is
root-owned while the notebook runs as uid 1000.


**Decision.** Launch and evaluation endpoints are rate limited by a small,
per-process token bucket keyed by `(user, action)`.

**Why.** It is a safety valve against accidental double-clicks and runaway
scripts, not a distributed quota system.

**Consequence.** With multiple backend replicas the effective limit is
`replicas × configured rate`. Cluster-wide quotas belong in the ingress or an
API gateway. This is documented rather than hidden.

## Session identity is bound to the hub username

**Decision.** A session JWT carries `sub` (user id) and `hub` (hub username).
Every request re-reads the user from the database and rejects the token if
`user.hub_username != payload["hub"]`.

**Why.** The hub username is the key used by JupyterHub storage. If it could
change under a live session, one user could inherit another's files.

## Notebook file names are server-generated

**Decision.** The browser never supplies a filesystem path. Titles are
slugified, validated against a strict regex, and de-duplicated server-side.

**Why.** Path traversal and cross-user file access become structurally
impossible rather than merely filtered.

## Dataset snippets carry no user input

**Decision.** `build_loading_snippet` composes the path from the manifest's
`relative_mount_path` and the configured mount point only. Format is chosen
from a fixed reader map (`csv → pd.read_csv`, `parquet → pd.read_parquet`,
`xlsx → pd.read_excel`).

**Why.** The browser can select a published dataset; it cannot contribute path
segments or code.

## Content is validated before seeding

**Decision.** `scripts/validate_content.py` enforces the seven-stage lesson
structure, known block types, dataset references, difficulty vocabulary and
exercise evaluation shape. `scripts/seed.py` refuses datasets whose file bytes
do not match the manifest checksum.

**Why.** Broken curriculum should fail in CI, not in a lesson.
