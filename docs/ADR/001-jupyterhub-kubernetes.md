# ADR-001: JupyterHub and Kubernetes rather than a custom notebook manager

**Status:** Accepted

## Context

OpenCS Labs must give up to 600 enrolled students a persistent, isolated
notebook workspace, with a peak of 400 concurrent notebook users. Each student
needs their own server, kernel lifecycle (start/restart/interrupt), file
persistence, idle shutdown and resource limits.

Building that from scratch means implementing:

- per-user server lifecycle and process supervision
- a proxy with per-user routing and authentication
- kernel management and the Jupyter server protocol
- idle detection and culling
- scheduling across multiple machines
- per-user storage mounting

That is a substantial, security-sensitive platform in its own right, and it is
not the product.

## Decision

Use **JupyterHub** as the notebook control plane, with:

- **KubeSpawner** on **Kubernetes** for per-user pods
- an **authenticator** that validates the OpenCS session JWT (single sign-on)
- a **single pinned analytics image** (`opencs/analytics:1.0.0`) for all
  students
- a **persistent volume per user** for notebook files
- the **dataset library** mounted read-only into every notebook pod

The FastAPI backend is the application, not the notebook manager. It talks to
JupyterHub's REST API for server state and to the user's server API for
contents, using a scoped token minted per user and never exposed to the
browser.

## Consequences

**Positive**

- We inherit a mature, security-reviewed proxy, spawner and kernel lifecycle.
- Per-user isolation is a Kubernetes property (namespace, PVC, pod security
  context), not bespoke code.
- Scaling is "add worker nodes"; scheduling, eviction and restarts are
  handled by the platform.
- The same image runs notebooks and the grading sandbox, so "works in the
  lesson" and "passes the checks" use identical libraries.

**Negative / costs**

- Operationally heavier than a single process: Kubernetes, a Hub, a proxy and
  persistent storage must be maintained.
- Debugging spans two systems; a notebook failure can be an application bug or
  a cluster issue.
- Local development needs a fallback. The Compose stack uses DockerSpawner for
  this reason; it is not the production topology.

## Alternatives considered

- **A custom FastAPI kernel manager.** Rejected: reimplements a security-
  critical surface, violates HLD rule 6, and delays the actual product.
- **JupyterHub with the default spawner on a single host.** Rejected as the
  production target because it does not isolate resources per student at the
  scale required, though it is retained for development via DockerSpawner.
- **Managed notebook services (Colab, SageMaker).** Rejected: no on-premises
  or self-hosted option meeting the "locally hosted datasets, isolated
  per-student storage" requirement.
