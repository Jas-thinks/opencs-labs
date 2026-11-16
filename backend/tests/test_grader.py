"""Tests for the grading sandbox abstraction.

The execution backend is faked; the parsing, scoring, availability checks and
error handling are real. This is the seam that must never fabricate a pass.
"""

from __future__ import annotations

import json

import pytest

from app.core import config as config_module
from app.core.errors import UpstreamUnavailable
from app.integrations import grader as grader_module
from app.integrations.grader import (
    RESULT_MARKER,
    DockerSandbox,
    GradeResult,
    NotebookGrader,
    result_to_feedback,
)


class RecordingSandbox:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0, available: bool = True):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self._available = available
        self.calls: list[object] = []

    def available(self) -> bool:
        return self._available

    def run(self, work):
        self.calls.append(work)
        # The staging directory must contain the two documents.
        assert (work / "notebook.json").is_file()
        assert (work / "checks.json").is_file()
        return self.stdout, self.stderr, self.returncode


def _result_line(payload: dict) -> str:
    return RESULT_MARKER + json.dumps(payload)


EVALUATION = {
    "tests": [
        {"id": "a", "description": "first", "code": "assert True"},
        {"id": "b", "description": "second", "code": "assert True"},
    ],
    "timeout_seconds": 5,
}


@pytest.fixture(autouse=True)
def _grader_enabled(monkeypatch):
    # Default settings use grader="docker"; these unit tests use a fake sandbox
    # so the CLI is never invoked.
    monkeypatch.setattr(config_module.settings, "grader", "docker", raising=False)


def test_parses_a_passing_result():
    stdout = _result_line(
        {
            "passed": True,
            "score": 1.0,
            "tests": [
                {"id": "a", "description": "first", "passed": True, "message": ""},
                {"id": "b", "description": "second", "passed": True, "message": ""},
            ],
            "error": None,
        }
    )
    result = NotebookGrader(sandbox=RecordingSandbox(stdout)).evaluate({}, EVALUATION)
    assert result.passed is True
    assert result.score == 1.0
    assert [test.id for test in result.tests] == ["a", "b"]


def test_partial_score_is_not_a_pass():
    stdout = _result_line(
        {
            "passed": False,
            "score": 0.5,
            "tests": [
                {"id": "a", "description": "first", "passed": True, "message": ""},
                {"id": "b", "description": "second", "passed": False, "message": "AssertionError"},
            ],
            "error": None,
        }
    )
    result = NotebookGrader(sandbox=RecordingSandbox(stdout)).evaluate({}, EVALUATION)
    assert result.passed is False
    assert result.score == 0.5
    assert result.tests[1].message == "AssertionError"


def test_missing_result_marker_never_passes():
    """A sandbox that prints nothing must not be interpreted as success."""
    result = NotebookGrader(sandbox=RecordingSandbox("no marker here", "boom", 1)).evaluate(
        {}, EVALUATION
    )
    assert result.passed is False
    assert result.score == 0.0
    assert result.error is not None
    assert "platform issue" in result.error


def test_malformed_result_line_never_passes():
    result = NotebookGrader(
        sandbox=RecordingSandbox(RESULT_MARKER + "{not json", "", 0)
    ).evaluate({}, EVALUATION)
    assert result.passed is False


def test_unavailable_sandbox_raises_instead_of_faking():
    sandbox = RecordingSandbox("", available=False)
    with pytest.raises(UpstreamUnavailable):
        NotebookGrader(sandbox=sandbox).evaluate({}, EVALUATION)
    assert sandbox.calls == []


def test_disabled_grader_raises(monkeypatch):
    monkeypatch.setattr(config_module.settings, "grader", "disabled", raising=False)
    with pytest.raises(UpstreamUnavailable):
        NotebookGrader().evaluate({}, EVALUATION)


def test_exercise_without_tests_raises():
    with pytest.raises(UpstreamUnavailable):
        NotebookGrader(sandbox=RecordingSandbox("")).evaluate({}, {"tests": []})


def test_feedback_shape_is_stable():
    result = GradeResult(
        passed=True,
        score=1.0,
        tests=[],
        error=None,
        duration_seconds=1.23,
    )
    feedback = result_to_feedback(result, attempt_count=2)
    assert feedback["passed"] is True
    assert feedback["score"] == 1.0
    assert feedback["attempt_number"] == 2
    assert "evaluated_at" in feedback


def test_docker_command_has_the_isolation_flags():
    command = DockerSandbox().command(__import__("pathlib").Path("/tmp/stage"))
    joined = " ".join(command)
    for flag in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges"):
        assert flag in joined
    assert "--pids-limit 256" in joined
    assert "/opt/opencs/datasets:ro" in joined
    assert grader_module.RUNNER_PATH in command


def test_kubernetes_job_spec_is_isolated():
    """The Job is the production sandbox; its isolation must not silently regress."""
    from app.integrations.grader import KubernetesSandbox

    job = KubernetesSandbox().build_job("opencs-grade-test")
    pod = job.spec.template.spec
    container = pod.containers[0]

    assert pod.restart_policy == "Never"
    assert pod.automount_service_account_token is False
    assert job.spec.backoff_limit == 0
    assert container.image == config_module.settings.grader_image
    assert container.command == ["python", grader_module.RUNNER_PATH, grader_module.SANDBOX_WORK_PATH]

    context = container.security_context
    assert context.run_as_non_root is True
    assert context.run_as_user == 1000
    assert context.allow_privilege_escalation is False
    assert context.read_only_root_filesystem is True
    assert context.capabilities.drop == ["ALL"]

    mounts = {mount.name: mount for mount in container.volume_mounts}
    assert mounts["datasets"].read_only is True
    assert mounts["datasets"].mount_path == grader_module.SANDBOX_DATASET_PATH
    assert mounts["staging"].mount_path == grader_module.SANDBOX_WORK_PATH

    volumes = {volume.name: volume for volume in pod.volumes}
    assert volumes["datasets"].persistent_volume_claim.read_only is True
    assert container.resources.limits["memory"] == config_module.settings.grader_memory
