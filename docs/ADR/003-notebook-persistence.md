# ADR-003: Notebook persistence and per-user isolation

**Status:** Accepted

## Context

Students must be able to save work and return to it later. Notebook files and
outputs must persist independently of kernel memory, and no student may read
another student's files. A kernel restart must not lose saved cells.

## Decision

**Two independent storage layers.**

1. **Notebook files** — a per-user Kubernetes PersistentVolumeClaim
   (`claim-<hub_username>`, ReadWriteOnce) mounted at `/home/opencs`. JupyterHub
   writes `.ipynb` files here. Files survive pod restarts, image upgrades and
   kernel deaths.
2. **Kernel memory** — ephemeral, inside the pod. It holds Python state only.

The backend keeps **metadata** (title, file name, kind, source reference,
environment image, timestamps) in PostgreSQL, but never the notebook body. The
body lives in the user's Jupyter storage and is fetched through the user's own
server API when needed (download, grading).

**Isolation** is enforced at four points:

- **Kubernetes** — each user gets their own pod, PVC and (optionally) network
  policy. Pods run as uid/gid 1000 with all capabilities dropped.
- **JupyterHub routing** — `/user/<name>/` routes only to that user's server.
- **Backend authorization** — every notebook operation resolves the owner from
  the authenticated session; a notebook that exists but is not owned is
  reported as `404`, indistinguishable from a missing one.
- **Server-generated file names** — the browser never supplies a path.

## Consequences

**Positive**

- "Save and reopen" works across restarts because the file is on the volume.
- Kernel crashes are not data loss.
- Cross-user access is denied structurally, and the denial does not leak
  existence.
- The backend stays stateless with respect to notebook bodies, so it can be
  replicated freely.

**Negative / costs**

- Listing notebooks can require a round-trip to the user's server to adopt
  files created directly in JupyterLab.
- Rename and delete must be applied to the volume, so they fail explicitly if
  the server is down rather than silently diverging.
- Storage sizing is per user; the cluster must provision enough PVCs for the
  enrolled class.

## Alternatives considered

- **Store notebook JSON in PostgreSQL.** Rejected: notebooks are files with
  large outputs and binary attachments; a database blob store would be a poor
  fit and would bypass the user's own Jupyter storage.
- **One shared volume for all users.** Rejected: destroys isolation.
- **Ephemeral storage with export/download only.** Rejected: contradicts the
  "return to your work tomorrow" requirement.
