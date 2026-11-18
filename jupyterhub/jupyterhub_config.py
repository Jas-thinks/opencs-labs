"""JupyterHub configuration for OpenCS Labs.

Topology (HLD.md section 16.2, docs/ADR/002):

    browser --ingress--> JupyterHub (this process) --KubeSpawner--> one Pod per student
                         |  auth: OpenCS session JWT (opencs_auth.py)
                         |  api : admin token for the FastAPI backend
                         +  idle-culling service

Everything is driven by environment variables, so the same image is deployed to
staging and production with only its config and secrets changed. Defaults are
development-safe and never contain production secrets.

Environment variables read here
-------------------------------
JUPYTERHUB_ADMIN_TOKEN          Hub admin token (dev stack); used as the
                                fallback for the backend's service token below
OPENCE_JUPYTERHUB_API_TOKEN     API token granted to the "opencs-backend" service
OPENCE_JWT_SECRET               Shared HS256 key with the backend (opencs_auth.py)
OPENCE_JWT_ISSUER               Expected session JWT issuer
OPENCE_SESSION_COOKIE           Browser cookie carrying the session JWT
OPENCE_NOTEBOOK_IMAGE           Single-user image   (default opencs/analytics:1.0.0)
OPENCE_DATASET_MOUNT_PATH       Dataset mount point (default /opt/opencs/datasets)
OPENCE_DATASET_SERVING_DIR      Host path of the dataset tree, checked if set
OPENCE_DATASET_PVC              Dataset PVC name    (default opencs-datasets)
OPENCE_POD_MEMORY               Memory request and limit      (default 2Gi)
OPENCE_POD_CPU                  CPU request and limit         (default 1)
OPENCE_POD_STORAGE              Per-student PVC size          (default 5Gi)
OPENCE_STORAGE_CLASS            StorageClass for user PVCs    (default standard)
OPENCE_HUB_NAMESPACE            Namespace for user pods       (default opencs-hub)
OPENCE_HUB_BIND_URL             Proxy bind URL (default http://0.0.0.0:8000)
OPENCE_HUB_PORT                 Hub API port   (default 8081)
OPENCE_HUB_CONNECT_URL          In-cluster URL pods use for the Hub API
OPENCE_HUB_DB_URL               Hub database  (default sqlite:///jupyterhub.sqlite)
OPENCE_IDLE_TIMEOUT_SECONDS     Idle cull timeout             (default 1800)
OPENCE_IDLE_CULL_EVERY_SECONDS  Cull interval                 (default 600)

The Hub's own public URL, cookie domain and proxy settings belong to the
deployment chart (infrastructure/helm), not to this file.
"""

from __future__ import annotations

import os
import sys

# `jupyterhub -f /srv/jupyterhub/jupyterhub_config.py` does not guarantee that the
# config's own directory is importable (a console script puts its own bin
# directory at sys.path[0]), so make `import opencs_auth` deterministic.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from opencs_auth import JWT_ISSUER, JWT_SECRET, SESSION_COOKIE, OpenCSAuthenticator


def _env(name: str, default: str) -> str:
    """Environment lookup that treats a blank value as absent."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


#: Kubernetes quantity suffix -> the suffix JupyterHub's ByteSpecification
#: accepts. Operators naturally write `2Gi` (valid in a pod spec) while
#: `Spawner.mem_limit` only understands K/M/G/T, and a mismatch is a hard
#: startup failure rather than a warning.
_MEMORY_UNITS = {
    "B": "",
    "K": "K",
    "M": "M",
    "G": "G",
    "T": "T",
    "KI": "K",
    "MI": "M",
    "GI": "G",
    "TI": "T",
    "KB": "K",
    "MB": "M",
    "GB": "G",
    "TB": "T",
}


def _memory_spec(value: str) -> int | str:
    """Normalise a Kubernetes memory quantity for ``Spawner.mem_limit``.

    ``2Gi`` -> ``2G``, ``512Mi`` -> ``512M``, ``2G`` -> ``2G``, ``2048`` ->
    ``2048`` (bytes, which is how JupyterHub treats a bare number). Anything
    unrecognised is returned unchanged so JupyterHub's own validation reports it
    rather than this helper silently guessing.
    """
    text = str(value).strip().replace(" ", "").upper()
    if not text:
        return 0
    if text.isdigit():
        return int(text)

    for suffix in sorted(_MEMORY_UNITS, key=len, reverse=True):
        if not text.endswith(suffix):
            continue
        digits = text[: -len(suffix)]
        if not digits or not digits.replace(".", "", 1).isdigit():
            continue
        unit = _MEMORY_UNITS[suffix]
        return digits if not unit else f"{digits}{unit}"
    return value


def _cpu_spec(value: str) -> float:
    """Normalise a Kubernetes CPU quantity to cores.

    ``1`` -> ``1.0`` and ``500m`` -> ``0.5``. ``Spawner.cpu_limit`` is a Float,
    so a millicore string would otherwise raise at startup.
    """
    text = str(value).strip().upper()
    if text.endswith("M") and text[:-1].replace(".", "", 1).isdigit():
        return float(text[:-1]) / 1000.0
    return float(text)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
ADMIN_TOKEN = _env("JUPYTERHUB_ADMIN_TOKEN", "")

# The backend authenticates to the Hub API with this token. In the dev stack it
# is the same value as JUPYTERHUB_ADMIN_TOKEN, so fall back to it rather than
# silently registering a service with no credential.
BACKEND_API_TOKEN = _env("OPENCE_JUPYTERHUB_API_TOKEN", ADMIN_TOKEN)

NOTEBOOK_IMAGE = _env("OPENCE_NOTEBOOK_IMAGE", "opencs/analytics:1.0.0")
DATASET_MOUNT_PATH = _env("OPENCE_DATASET_MOUNT_PATH", "/opt/opencs/datasets").rstrip("/")
DATASET_PVC = _env("OPENCE_DATASET_PVC", "opencs-datasets")
DATASET_SERVING_DIR = _env("OPENCE_DATASET_SERVING_DIR", "")

POD_MEMORY = _env("OPENCE_POD_MEMORY", "2Gi")
POD_CPU = _env("OPENCE_POD_CPU", "1")
POD_STORAGE = _env("OPENCE_POD_STORAGE", "5Gi")
STORAGE_CLASS = _env("OPENCE_STORAGE_CLASS", "standard")

HUB_NAMESPACE = _env("OPENCE_HUB_NAMESPACE", "opencs-hub")
BIND_URL = _env("OPENCE_HUB_BIND_URL", "http://0.0.0.0:8000")
HUB_CONNECT_URL = _env("OPENCE_HUB_CONNECT_URL", "")
HUB_DB_URL = _env("OPENCE_HUB_DB_URL", "sqlite:///jupyterhub.sqlite")
# Public URL the browser must use for this Hub. When the host publishes a mapped
# port (for example http://10.1.75.79:5221), set it here so redirects, cookies
# and generated /user/... links are built from the external address instead of
# the internal interface the proxy actually binds to.
PUBLIC_URL = _env("OPENCE_JUPYTERHUB_PUBLIC_URL", "")
PROXY_PUBLIC_URL = _env("OPENCE_PROXY_PUBLIC_URL", PUBLIC_URL)

IDLE_TIMEOUT_SECONDS = int(_env("OPENCE_IDLE_TIMEOUT_SECONDS", "1800"))
IDLE_CULL_EVERY_SECONDS = int(_env("OPENCE_IDLE_CULL_EVERY_SECONDS", "600"))

# --------------------------------------------------------------------------- #
# Hub itself
# --------------------------------------------------------------------------- #
c.JupyterHub.bind_url = BIND_URL

# Path prefix for a sharded deployment. Each Hub shard is served by the edge
# under its own prefix (/nb/0/, /nb/1/, ...) on the application's origin, so the
# OpenCS session cookie reaches /hub/login (single sign-on) and the JupyterLab
# extension's credentialed calls to /api/v1 are same-origin. Hub and per-user
# cookies are path-scoped to the prefix, so shards never collide.
HUB_BASE_URL = _env("OPENCE_HUB_BASE_URL", "/")
if not HUB_BASE_URL.endswith("/"):
    HUB_BASE_URL += "/"
c.JupyterHub.base_url = HUB_BASE_URL

# Cap on concurrently running user servers on this Hub; 0 = unlimited. Beyond
# it the Hub answers 429 and the backend reports "capacity exhausted" instead of
# letting one more kernel OOM a memory-capped node.
c.JupyterHub.active_server_limit = int(_env("OPENCE_ACTIVE_SERVER_LIMIT", "0"))

# The configurable HTTP proxy (CHP) is the only public listener. It serves the
# browser on port 8000 and exposes its control API on 8001; the Hub itself must
# therefore listen elsewhere or it collides with the proxy API. Keep the Hub on
# 8081 (the port the backend calls, see OPENCE_JUPYTERHUB_API_URL) and let the
# proxy own 8000/8001.
c.JupyterHub.hub_ip = _env("OPENCE_HUB_IP", "0.0.0.0")
c.JupyterHub.hub_port = int(_env("OPENCE_HUB_PORT", "8081"))
c.ConfigurableHTTPProxy.command = "configurable-http-proxy"
c.JupyterHub.log_level = "INFO"
c.JupyterHub.db_url = HUB_DB_URL

# External-address handling.
#
# The proxy binds on 0.0.0.0:PORT inside the container, but the browser reaches
# it through a host-mapped port (http://10.1.75.79:5221). Without these two
# settings JupyterHub builds absolute URLs and redirects from the internal
# socket, which leaks the container address into the browser.
#
# ``public_url`` tells the configurable proxy the address clients actually use,
# so it rewrites Location headers and generated routes to it.
if PROXY_PUBLIC_URL:
    c.ConfigurableHTTPProxy.public_url = PROXY_PUBLIC_URL

# Honour X-Forwarded-Host from a trusted front proxy. Empty means "use the
# request's own Host header", which is already the mapped external host when the
# browser talks to 10.1.75.79:5221 directly.
_forwarded_host = _env("OPENCE_FORWARDED_HOST_HEADER", "")
if _forwarded_host:
    c.JupyterHub.forwarded_host_header = _forwarded_host

# Cross-origin note (no extra trait needed in JupyterHub 4):
# the SPA at http://10.1.75.53:6306 and the notebook at
# http://10.1.75.79:5221 are different origins. Opening a notebook is a
# top-level navigation to the notebook origin, so the Hub cookie is set and
# sent for that host directly; the SPA never needs to make credentialed
# cross-origin XHR calls to the notebook. JupyterHub 4 removed the 3.x
# `allow_origin` trait, and `trust_xheaders` is likewise absent, so setting
# either would fail at startup. The mapped public URL above is what makes the
# generated links external.
SPA_ORIGIN = _env("OPENCE_PUBLIC_ORIGIN", "").rstrip("/")

# The only way in is the OpenCS session JWT (see opencs_auth.py). There is no
# password form and no local user database of passwords, so a student who is
# signed in to the course app is never asked to sign in again.
c.JupyterHub.authenticator_class = OpenCSAuthenticator

# Referenced by entry-point name: a missing kubespawner installation then fails
# at startup instead of silently falling back to local process spawning.
#
# OPENCE_SPAWNER=docker selects DockerSpawner for the single-host Compose stack.
# Kubernetes remains the production topology (docs/ADR/001); the Docker path
# exists so the whole stack can run locally without a cluster.
SPAWNER = _env("OPENCE_SPAWNER", "kubernetes").strip().lower()

if SPAWNER == "local":
    # Native host-process spawning for deployments with no Docker, no Kubernetes
    # and no systemd (the 12-endpoint tmux deployment). Each Hub node runs its
    # own LocalProcessSpawner; per-user servers are ordinary processes under a
    # single OS user, so there is no cross-user kernel isolation. Documented in
    # docs/deployment/ rather than implied.
    #
    # OpenCSLocalSpawner calls pwd.getpwnam(user.name) in user_env(), which needs
    # one OS account per Hub user. These targets have no per-student accounts.
    import pwd as _pwd

    _service_user = _env("OPENCE_HUB_SERVICE_USER", "") or _pwd.getpwuid(os.getuid()).pw_name
    _home = _env("OPENCE_NOTEBOOK_HOME", "/home/student/opencs-runtime/notebooks")
    # OpenCSLocalSpawner subclasses LocalProcessSpawner and removes the passwd
    # lookup for the Hub username (see opencs_local_spawner.py). The stock
    # spawner cannot run here because usernames like "student1" have no OS
    # account on these targets.
    c.JupyterHub.spawner_class = "opencs_local_spawner.OpenCSLocalSpawner"
    c.Spawner.service_user = _service_user
    c.Spawner.home_root = _home
    c.Spawner.cmd = [_env("OPENCE_SINGLEUSER_CMD", "jupyterhub-singleuser")]
    c.Spawner.default_url = "/lab"
    c.Spawner.http_timeout = int(_env("OPENCE_SPAWN_HTTP_TIMEOUT", "180"))
    c.Spawner.start_timeout = int(_env("OPENCE_SPAWN_START_TIMEOUT", "120"))
    # Root each server at the user's own directory. Rooting it at the shared
    # home tree let every student browse every other student's notebooks.
    c.Spawner.notebook_dir = os.path.join(_home, "{username}")
    # One BLAS/OpenMP thread per kernel: the node has a 1-CPU cgroup, and the
    # libraries otherwise size thread pools from the host's 120 visible cores,
    # which costs memory and thrashes the single CPU.
    c.Spawner.environment = {
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_MAX_THREADS": "1",
    }
elif SPAWNER == "docker":
    c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
    c.DockerSpawner.image = NOTEBOOK_IMAGE
    c.DockerSpawner.network_name = _env("DOCKER_NETWORK_NAME", "opencs-labs_default")
    c.DockerSpawner.remove = True
    # Per-student home on a named Docker volume. `remove = True` deletes the
    # *container* on stop, which is the whole point (no orphans); without a
    # volume it would also delete the student's notebooks, so persistence has to
    # live outside the container filesystem. DockerSpawner names it
    # `jupyter-<username>` by default.
    c.DockerSpawner.use_internal_ip = True
    c.DockerSpawner.volumes = {
        # Per-user home: survives container removal, holds notebooks + outputs.
        "jupyter-{username}": "/home/opencs",
        # Same absolute path as the host and the backend container, so the
        # lesson snippet ("/opt/opencs/datasets/...") resolves in the notebook.
        DATASET_SERVING_DIR or "opencs-datasets": {
            "bind": DATASET_MOUNT_PATH,
            "mode": "ro",
        },
    }
    c.DockerSpawner.notebook_dir = "/home/opencs"
    # A freshly created named volume is owned by root, but the notebook runs as
    # uid 1000. DockerSpawner already has a Docker client, so use it rather than
    # shelling out (the Hub image has no `docker` CLI).
    def _fix_volume_ownership(spawner):  # noqa: ANN001 - DockerSpawner hook
        """Chown the per-user home volume to uid/gid 1000.

        A freshly created named volume is owned by root while the notebook runs
        as uid 1000. DockerSpawner exposes a low-level docker APIClient, so the
        chown runs as a throwaway container through it (the Hub image has no
        `docker` CLI).
        """
        volume = f"jupyter-{spawner.user.name}"
        try:
            client = spawner.client
            existing = {v["Name"] for v in (client.volumes().get("Volumes") or [])}
            if volume not in existing:
                client.create_volume(volume)
            container = client.create_container(
                image=spawner.image or NOTEBOOK_IMAGE,
                command=["chown", "-R", "1000:1000", "/home/opencs"],
                volumes=["/home/opencs"],
                host_config=client.create_host_config(
                    binds={volume: {"bind": "/home/opencs", "mode": "rw"}}
                ),
            )
            client.start(container["Id"])
            client.wait(container["Id"])
            client.remove_container(container["Id"], force=True)
        except Exception as exc:  # noqa: BLE001 - never block a spawn on this
            spawner.log.warning("could not prepare home volume %s: %s", volume, exc)

    c.DockerSpawner.pre_spawn_hook = _fix_volume_ownership
    c.DockerSpawner.cmd = [
        "/bin/sh",
        "-c",
        'exec jupyterhub-singleuser --ip=0.0.0.0 --port=8888 '
        '--ServerApp.base_url="${JUPYTERHUB_SERVICE_PREFIX:-/}"',
    ]
    # DockerSpawner/Spawner want the Docker-style quantity (2G), not the
    # Kubernetes one (2Gi); _memory_spec bridges them.
    c.DockerSpawner.mem_limit = _memory_spec(POD_MEMORY)
    c.DockerSpawner.cpu_limit = _cpu_spec(POD_CPU)
elif SPAWNER == "kubernetes":
    c.JupyterHub.spawner_class = "kubespawner.KubeSpawner"

# JupyterHub can persist `auth_state` (OpenCS user id/role/email) so the
# platform's records can be reconciled without trusting anything from the
# browser. Encryption requires JUPYTERHUB_CRYPT_KEY; without it JupyterHub
# refuses to store auth_state at all, so enabling the flag alone is misleading.
# Enable it only when a key is actually configured.
if _env("JUPYTERHUB_CRYPT_KEY", "").strip():
    c.Authenticator.enable_auth_state = True
else:
    c.Authenticator.enable_auth_state = False

# Servers are stopped when the Hub stops, so a rollout cannot leave orphaned pods
# behind. Logging out of the notebook does not stop the server: a student who
# steps back into the course app keeps their work.
c.JupyterHub.cleanup_servers = True
c.JupyterHub.shutdown_on_logout = False

# NOTE: the proxy command is deliberately left at its default
# (`configurable-http-proxy`, installed in the hub image). Overriding it is how
# most deployments break on upgrade.

# --------------------------------------------------------------------------- #
# Single-user pods
# --------------------------------------------------------------------------- #
c.Spawner.default_url = "/lab"
c.Spawner.debug = False
c.Spawner.start_timeout = 300
c.Spawner.http_timeout = 60

if SPAWNER == "kubernetes":
    # KubeSpawner traitlets (production). In DockerSpawner mode these belong to
    # a class that is not the active spawner, so they are only set here.
    c.KubeSpawner.image = NOTEBOOK_IMAGE
    c.KubeSpawner.image_pull_policy = "IfNotPresent"
    c.KubeSpawner.namespace = HUB_NAMESPACE
    c.KubeSpawner.working_dir = "/home/opencs/work"

    # The analytics image is a plain JupyterLab install (it has no
    # `jupyterhub-singleuser` entry point), so the Hub starts it through `sh`.
    # JupyterHub injects JUPYTERHUB_SERVICE_PREFIX=/user/<name>/ and the proxy
    # forwards that path unchanged, so the server must bind its base_url to it; a
    # server bound at "/" would 404 on every page.
    #
    # Token and password are disabled because authentication happens in JupyterHub
    # *in front of* this server (opencs_auth.py). The consequence worth knowing: the
    # JupyterLab process does not itself validate the Hub cookie, so /user/<name>/
    # must only be reachable through the Hub proxy -- one ingress origin, never a
    # direct route to notebook pods.
    c.KubeSpawner.cmd = [
        "/bin/sh",
        "-c",
        'exec jupyterhub-singleuser --ip=0.0.0.0 --port=8888 '
        '--ServerApp.base_url="${JUPYTERHUB_SERVICE_PREFIX:-/}"',
    ]

    # Requests equal limits: a notebook pod is bursty, and an equal profile keeps
    # scheduling predictable while stopping one runaway training loop from starving a
    # neighbour on the same node. Both are normalised because JupyterHub's memory
    # trait accepts K/M/G/T while operators write Kubernetes quantities (`2Gi`).
    c.KubeSpawner.cpu_guarantee = _cpu_spec(POD_CPU)
    c.KubeSpawner.cpu_limit = _cpu_spec(POD_CPU)
    c.KubeSpawner.mem_guarantee = _memory_spec(POD_MEMORY)
    c.KubeSpawner.mem_limit = _memory_spec(POD_MEMORY)

    # --------------------------------------------------------------------------- #
    # Identity and pod hardening
    # --------------------------------------------------------------------------- #
    # uid/gid 1000 match notebook-image/Dockerfile's `opencs` user and the host side
    # of every mounted volume. fsGroup 1000 makes mounted PVCs usable by that uid.
    c.KubeSpawner.uid = 1000
    c.KubeSpawner.gid = 1000
    c.KubeSpawner.fs_gid = 1000

    # Maps onto the notebook container's securityContext. runAsUser/runAsGroup come
    # from uid/gid above and fsGroup from fs_gid; the rest has no dedicated
    # KubeSpawner traitlet, so it is set here.
    c.KubeSpawner.container_security_context = {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
        # Deliberately writable: several pinned wheels (numba, matplotlib's font
        # cache, IPython history) want a writable site directory on first import,
        # and a read-only root breaks genuine student workflows. Everything a student
        # produces lives on their PVC, not in the image.
        "readOnlyRootFilesystem": False,
    }

    # A notebook pod is an ordinary workload and must not be able to reach the
    # Kubernetes API or inherit the platform's service environment.
    c.KubeSpawner.extra_pod_config = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "restartPolicy": "OnFailure",
    }

    # --------------------------------------------------------------------------- #
    # Storage
    # --------------------------------------------------------------------------- #
    # One PersistentVolumeClaim per student, mounted at their home directory, so
    # notebooks survive a pod restart or an image rollout.
    c.KubeSpawner.pvc_name_template = "claim-{username}"
    c.KubeSpawner.storage_pvc_ensure = True
    c.KubeSpawner.storage_class = STORAGE_CLASS
    c.KubeSpawner.storage_access_modes = ["ReadWriteOnce"]
    c.KubeSpawner.storage_capacity = POD_STORAGE

    c.KubeSpawner.volumes = [
        # The student's own home: notebooks, kernel files, ~/.local.
        {"name": "home", "persistentVolumeClaim": {"claimName": "claim-{username}"}},
        # Canonical datasets: shared, centrally versioned, read-only. Nothing in a
        # notebook pod may write here (HLD.md 10.7).
        {
            "name": "datasets",
            "persistentVolumeClaim": {"claimName": DATASET_PVC, "readOnly": True},
        },
        # Some numerical libraries use /dev/shm for worker shared memory; the
        # container default of 64MiB produces confusing "bus error" failures.
        {"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"}},
        # Writable, bounded, pod-scoped scratch space.
        {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
    ]

    c.KubeSpawner.volume_mounts = [
        {"name": "home", "mountPath": "/home/opencs"},
        {"name": "datasets", "mountPath": DATASET_MOUNT_PATH, "readOnly": True},
        {"name": "shm", "mountPath": "/dev/shm"},
        {"name": "tmp", "mountPath": "/tmp"},
    ]

    # How a spawned pod reaches the Hub API for its own activity pings. Unset means
    # "derive it from the Hub's own URL", which is correct inside one cluster; a
    # deployment behind NAT or a split hostname sets it explicitly.
    if HUB_CONNECT_URL:
        c.KubeSpawner.hub_connect_url = HUB_CONNECT_URL

# --------------------------------------------------------------------------- #
# Services and roles
# --------------------------------------------------------------------------- #
# Idle culling: stop a student's server after IDLE_TIMEOUT_SECONDS without an
# activity ping. --max-age=0 means an active session is never culled for age
# alone, only for inactivity (HLD.md FR-053).
#
# `admin: True` grants the built-in `admin` role (still supported in JupyterHub
# 4, although `load_roles` is the modern mechanism). The named roles below are
# the narrower contract each service actually needs; with `admin: True` the
# effective scope set is the union, i.e. broader. Dropping the flag leaves the
# platform working on the named roles alone, if a deployment's RBAC review
# prefers that.
c.JupyterHub.services = [
    {
        "name": "idle-culler",
        "admin": True,
        "command": [
            sys.executable,
            "-m",
            "jupyterhub_idle_culler",
            f"--timeout={IDLE_TIMEOUT_SECONDS}",
            f"--cull-every={IDLE_CULL_EVERY_SECONDS}",
            "--max-age=0",
        ],
    },
    {
        # The FastAPI backend, the only holder of a Hub API token. The browser
        # never receives one (HLD.md 10.7).
        "name": "opencs-backend",
        "admin": True,
        "api_token": BACKEND_API_TOKEN,
    },
]

# Roles are assigned by service membership. The scopes are listed explicitly so
# the contract the backend and the idle culler depend on is visible in one place
# and survives changes to the default role definitions.
c.JupyterHub.load_roles = [
    {
        "name": "idle-culler",
        "description": "Stop idle notebook pods (jupyterhub-idle-culler)",
        "services": ["idle-culler"],
        "scopes": [
            "read:users",
            "list:users",
            "admin:servers",
            "read:servers",
            "delete:servers",
        ],
    },
    {
        "name": "opencs-backend",
        "description": "FastAPI backend: launch, poll and stop student notebooks",
        "services": ["opencs-backend"],
        "scopes": [
            "admin:users",
            "admin:servers",
            "read:users",
            "servers",
            "tokens",
        ],
    },
]

# --------------------------------------------------------------------------- #
# Startup validation
# --------------------------------------------------------------------------- #
# JupyterHub starts perfectly well with a broken SSO configuration and then fails
# per-request, which is easy to miss during a rollout. These warnings put the
# misconfiguration in the Hub log at boot instead.
_warnings: list[str] = []

if not BACKEND_API_TOKEN:
    _warnings.append(
        "OPENCE_JUPYTERHUB_API_TOKEN is empty: the OpenCS backend can neither "
        "launch nor stop notebooks. Use the same value as the backend."
    )
if not JWT_SECRET:
    _warnings.append(
        "OPENCE_JWT_SECRET is empty: no OpenCS session token can be verified and "
        "no student can log in."
    )
if not JWT_ISSUER:
    _warnings.append("OPENCE_JWT_ISSUER is empty: the backend issues 'opencs'.")
if not SESSION_COOKIE:
    _warnings.append("OPENCE_SESSION_COOKIE is empty: the browser cookie is not read.")
if not _env("JUPYTERHUB_CRYPT_KEY", "").strip():
    _warnings.append(
        "JUPYTERHUB_CRYPT_KEY is empty: auth_state is not persisted, so the "
        "backend cannot read a Hub user's OpenCS id/role from stored auth. "
        "Set a Fernet key to enable it."
    )
if DATASET_SERVING_DIR and not os.path.isdir(DATASET_SERVING_DIR):
    _warnings.append(
        f"OPENCE_DATASET_SERVING_DIR ({DATASET_SERVING_DIR}) does not exist: "
        "materialise the dataset tree before students load data."
    )
if DATASET_MOUNT_PATH.count("/") < 2:
    _warnings.append(
        f"OPENCE_DATASET_MOUNT_PATH ({DATASET_MOUNT_PATH}) does not look like an "
        "absolute container path."
    )

for _message in _warnings:
    print(f"[jupyterhub_config] WARNING: {_message}", file=sys.stderr, flush=True)
# `del _message` only exists if the loop ran; deleting it unconditionally
# crashes the Hub whenever the configuration is clean.
if _warnings:
    del _message
del _warnings
