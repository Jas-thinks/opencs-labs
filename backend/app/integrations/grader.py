"""Practice evaluation in an isolated sandbox.

Student notebook code is executed inside a short-lived container built from the
same pinned analytics image used for notebooks. The FastAPI process never
executes student code.

Two execution strategies share one contract:

``docker``
    Local development and the single-host Compose stack. Runs
    ``docker run --network none ... opencs/analytics:1.0.0 python
    /opt/opencs/grade_runner.py /work``.

``kubernetes``
    Production. Creates a ``batch/v1`` Job from the same pinned image with the
    same isolation (no service-account token, all capabilities dropped,
    read-only root filesystem, resource limits) and reads the result line from
    the pod log. This is the HLD's production path: the hardened backend pod
    has no Docker daemon, so shelling out to ``docker`` cannot work there.

Both strategies emit the same single ``###OPENCE_RESULT###`` line, so parsing
and scoring are shared. If a sandbox is unavailable the API fails explicitly
rather than pretending an evaluation happened.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from app.core.config import settings
from app.core.errors import UpstreamUnavailable
from app.core.metrics import GRADER_LATENCY, GRADER_RUNS

logger = logging.getLogger("opencs.grader")

RESULT_MARKER = "###OPENCE_RESULT###"

#: Path of the runner inside the analytics image.
RUNNER_PATH = "/opt/opencs/grade_runner.py"

#: Staging directory the sandbox mounts read/write.
SANDBOX_WORK_PATH = "/work"

#: Directory the sandbox mounts the dataset tree at (read-only).
SANDBOX_DATASET_PATH = "/opt/opencs/datasets"


@dataclass
class GradeTest:
    id: str
    description: str
    passed: bool
    message: str = ""


@dataclass
class GradeResult:
    passed: bool
    score: float
    tests: list[GradeTest] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0


class Sandbox(Protocol):
    """One strategy for running the grade runner over a staging directory."""

    def available(self) -> bool: ...

    def run(self, work: Path) -> tuple[str, str, int]: ...


class DockerSandbox:
    """Runs the grader with the local Docker daemon."""

    def available(self) -> bool:
        return shutil.which("docker") is not None

    def command(self, work: Path) -> list[str]:
        serving = settings.serving_dir
        stats = serving.stat() if serving.exists() else None
        user = f"{stats.st_uid}:{stats.st_gid}" if stats else "1000:1000"
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            settings.grader_memory,
            "--cpus",
            settings.grader_cpus,
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            user,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "-e",
            "MPLBACKEND=Agg",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{work}:{SANDBOX_WORK_PATH}:rw",
            "-v",
            f"{serving}:{SANDBOX_DATASET_PATH}:ro",
            settings.grader_image,
            "python",
            RUNNER_PATH,
            SANDBOX_WORK_PATH,
        ]

    def run(self, work: Path) -> tuple[str, str, int]:
        completed = subprocess.run(
            self.command(work),
            capture_output=True,
            text=True,
            timeout=settings.grader_timeout_seconds + 30,
            check=False,
        )
        return completed.stdout, completed.stderr, completed.returncode


class KubernetesSandbox:
    """Runs the grader as a short-lived Kubernetes Job.

    The Job mirrors the Docker invocation: one container from the pinned
    analytics image, the rendered notebook and checks supplied through a
    ConfigMap, the dataset PVC mounted read-only, no service-account token, all
    capabilities dropped and resource limits enforced. Egress is denied by the
    grader namespace's NetworkPolicy rather than ``--network none``.
    """

    def __init__(self) -> None:
        self.namespace = settings.grader_k8s_namespace
        self._api: Any = None

    def available(self) -> bool:
        try:
            import kubernetes  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self):
        """Import the Kubernetes client module.

        Deliberately does NOT load cluster credentials: building a Job object is
        pure data construction. Configuration is loaded only when a Job is
        actually created, so the spec can be inspected and tested without a
        reachable cluster.
        """
        if self._api is None:
            from kubernetes import client as k8s

            self._api = k8s
        return self._api

    def _api_client(self):
        """A configured client, loading in-cluster or kubeconfig credentials."""
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception:  # noqa: BLE001 - local use falls back to kubeconfig
            k8s_config.load_kube_config()
        k8s = self._client()
        return k8s.CoreV1Api(), k8s.BatchV1Api()

    def build_job(self, name: str) -> Any:
        k8s = self._client()
        labels = {"app.kubernetes.io/name": "opencs-grader", "opencs/job": name}
        container = k8s.V1Container(
            name="grade",
            image=settings.grader_image,
            command=["python", RUNNER_PATH, SANDBOX_WORK_PATH],
            env=[
                k8s.V1EnvVar(name="MPLBACKEND", value="Agg"),
                k8s.V1EnvVar(name="PYTHONDONTWRITEBYTECODE", value="1"),
            ],
            resources=k8s.V1ResourceRequirements(
                requests={"cpu": settings.grader_cpus, "memory": settings.grader_memory},
                limits={"cpu": settings.grader_cpus, "memory": settings.grader_memory},
            ),
            security_context=k8s.V1SecurityContext(
                run_as_non_root=True,
                run_as_user=1000,
                run_as_group=1000,
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=k8s.V1Capabilities(drop=["ALL"]),
                seccomp_profile=k8s.V1SeccompProfile(type="RuntimeDefault"),
            ),
            volume_mounts=[
                k8s.V1VolumeMount(name="staging", mount_path=SANDBOX_WORK_PATH),
                k8s.V1VolumeMount(
                    name="datasets", mount_path=SANDBOX_DATASET_PATH, read_only=True
                ),
                k8s.V1VolumeMount(name="tmp", mount_path="/tmp"),
            ],
        )
        pod_spec = k8s.V1PodSpec(
            restart_policy="Never",
            automount_service_account_token=False,
            active_deadline_seconds=int(settings.grader_timeout_seconds) + 60,
            containers=[container],
            volumes=[
                k8s.V1Volume(
                    name="staging",
                    config_map=k8s.V1ConfigMapVolumeSource(
                        name=name,
                        items=[
                            k8s.V1KeyToPath(key="notebook.json", path="notebook.json"),
                            k8s.V1KeyToPath(key="checks.json", path="checks.json"),
                        ],
                    ),
                ),
                k8s.V1Volume(
                    name="datasets",
                    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                        claim_name=settings.grader_dataset_pvc, read_only=True
                    ),
                ),
                k8s.V1Volume(name="tmp", empty_dir=k8s.V1EmptyDirVolumeSource(size_limit="256Mi")),
            ],
        )
        return k8s.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s.V1ObjectMeta(name=name, namespace=self.namespace, labels=labels),
            spec=k8s.V1JobSpec(
                backoff_limit=0,
                ttl_seconds_after_finished=300,
                template=k8s.V1PodTemplateSpec(
                    metadata=k8s.V1ObjectMeta(labels=labels), spec=pod_spec
                ),
            ),
        )

    def run(self, work: Path) -> tuple[str, str, int]:
        import uuid

        k8s = self._client()
        name = f"opencs-grade-{uuid.uuid4().hex[:12]}"
        notebook = (work / "notebook.json").read_text()
        checks = (work / "checks.json").read_text()

        core, batch = self._api_client()
        core.create_namespaced_config_map(
            namespace=self.namespace,
            body=k8s.V1ConfigMap(
                metadata=k8s.V1ObjectMeta(name=name, namespace=self.namespace),
                data={"notebook.json": notebook, "checks.json": checks},
            ),
        )
        try:
            batch.create_namespaced_job(namespace=self.namespace, body=self.build_job(name))
            deadline = time.monotonic() + settings.grader_timeout_seconds + 90
            status = None
            while time.monotonic() < deadline:
                status = batch.read_namespaced_job_status(name, self.namespace).status
                if status.succeeded or status.failed:
                    break
                time.sleep(2)
            pods = core.list_namespaced_pod(self.namespace, label_selector=f"opencs/job={name}").items
            if not pods:
                return "", "the grading pod never started", 1
            stdout = core.read_namespaced_pod_log(pods[0].metadata.name, self.namespace)
            return stdout, "", 0 if (status and status.succeeded) else 1
        finally:
            try:
                batch.delete_namespaced_job(name, self.namespace, propagation_policy="Background")
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                logger.warning("job cleanup failed for %s: %s", name, exc)
            try:
                core.delete_namespaced_config_map(name, self.namespace)
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                logger.warning("configmap cleanup failed for %s: %s", name, exc)


def _sandbox() -> Sandbox:
    if settings.grader == "kubernetes":
        return KubernetesSandbox()
    return DockerSandbox()


@contextmanager
def _staging_directory() -> Iterator[Path]:
    """A per-evaluation staging directory the sandbox can bind-mount.

    When the backend runs inside a container and starts sibling containers via
    the host daemon, the daemon resolves a bind-mount source on the HOST. A
    plain ``TemporaryDirectory`` therefore mounts an empty directory (the
    notebook is "missing" inside the sandbox). ``OPENCE_GRADER_STAGING_DIR``
    names a path that exists identically on host and backend container; each run
    gets a fresh subdirectory and it is removed afterwards either way.
    """
    base = settings.grader_staging_dir.strip()
    if base:
        root = Path(base)
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="opencs-grade-", dir=str(root)))
        try:
            yield work
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return

    with tempfile.TemporaryDirectory(prefix="opencs-grade-") as tmp:
        yield Path(tmp)


class NotebookGrader:
    def __init__(self, image: str | None = None, sandbox: Sandbox | None = None) -> None:
        self.image = image or settings.grader_image
        self._sandbox = sandbox

    def available(self) -> bool:
        if settings.grader == "disabled":
            return False
        return (self._sandbox or _sandbox()).available()

    def evaluate(self, notebook: dict[str, Any], evaluation: dict[str, Any]) -> GradeResult:
        if settings.grader == "disabled":
            raise UpstreamUnavailable(
                "Automated evaluation is disabled on this deployment",
                details={"hint": "set OPENCE_GRADER=docker or kubernetes"},
            )
        checks = {
            "tests": evaluation.get("tests", []),
            "timeout_seconds": int(
                evaluation.get("timeout_seconds", settings.grader_timeout_seconds)
            ),
        }
        if not checks["tests"]:
            raise UpstreamUnavailable("This exercise has no automated checks configured")

        sandbox = self._sandbox or _sandbox()
        if not sandbox.available():
            raise UpstreamUnavailable(
                "The grading sandbox is unavailable on this deployment",
                details={"grader": settings.grader},
            )

        started = time.perf_counter()
        with _staging_directory() as work:
            (work / "notebook.json").write_text(json.dumps(notebook))
            (work / "checks.json").write_text(json.dumps(checks))
            (work / "work").mkdir()
            try:
                stdout, stderr, returncode = sandbox.run(work)
            except subprocess.TimeoutExpired as exc:
                GRADER_RUNS.labels("timeout").inc()
                raise UpstreamUnavailable(
                    "Evaluation timed out; check for long-running or infinite code",
                    details={"timeout_seconds": settings.grader_timeout_seconds},
                ) from exc
            finally:
                GRADER_LATENCY.observe(time.perf_counter() - started)

            duration = round(time.perf_counter() - started, 2)
            result = self._parse(stdout, stderr, duration, returncode)

        if result.passed:
            GRADER_RUNS.labels("passed").inc()
        else:
            GRADER_RUNS.labels("failed").inc()
        return result

    @staticmethod
    def _parse(stdout: str, stderr: str, duration: float, returncode: int) -> GradeResult:
        for line in stdout.splitlines():
            if line.startswith(RESULT_MARKER):
                try:
                    payload = json.loads(line[len(RESULT_MARKER) :])
                except json.JSONDecodeError:
                    break
                tests = [
                    GradeTest(
                        id=item.get("id", "check"),
                        description=item.get("description", ""),
                        passed=bool(item.get("passed")),
                        message=item.get("message", ""),
                    )
                    for item in payload.get("tests", [])
                ]
                return GradeResult(
                    passed=bool(payload.get("passed")),
                    score=float(payload.get("score", 0.0)),
                    tests=tests,
                    error=payload.get("error"),
                    duration_seconds=duration,
                )
        logger.error("grader produced no result (rc=%s): %s", returncode, stderr[-800:])
        return GradeResult(
            passed=False,
            score=0.0,
            tests=[],
            error=(
                "The evaluation sandbox did not produce a result. "
                "This is a platform issue, not necessarily a mistake in your code."
            ),
            duration_seconds=duration,
        )


def result_to_feedback(result: GradeResult, attempt_count: int) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "score": round(result.score, 3),
        "tests": [asdict(test) for test in result.tests],
        "error": result.error,
        "duration_seconds": result.duration_seconds,
        "attempt_number": attempt_count,
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def get_grader() -> NotebookGrader:
    return NotebookGrader()
