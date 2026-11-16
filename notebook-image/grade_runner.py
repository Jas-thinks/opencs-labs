#!/usr/bin/env python3
"""Execute a student notebook plus its assertion checks inside the grading sandbox.

This file is the *inside* half of the grading contract. The FastAPI backend never
executes student code: it stages two JSON documents in a temporary directory and
runs this script in a network-less, resource-limited container built from the
pinned analytics image::

    docker run --rm ... opencs/analytics:1.0.0 python /opt/opencs/grade_runner.py /work

Inputs, relative to the staging root given on the command line:

``notebook.json``
    A standard ``.ipynb`` document: ``{"cells": [...]}`` where each cell has a
    ``cell_type`` and a ``source`` that may be a string or a list of strings.

``checks.json``
    ``{"tests": [{"id": str, "description": str, "code": str}, ...],
       "timeout_seconds": int}``

Execution model
---------------
1. ``chdir`` into ``<root>/work`` (created when missing), then execute every code
   cell in document order in one shared namespace with ``__name__`` set to
   ``"__main__"`` -- exactly what running the notebook top to bottom does.
2. Execute each check's ``code`` against that same namespace. A check passes when
   its ``exec`` raises nothing; the recorded message is ``Type: message``.
3. Write exactly one line to stdout: ``###OPENCE_RESULT###`` followed by compact
   JSON ``{"passed", "score", "tests", "error"}``. All human-readable logging and
   everything student code prints goes to stderr, so the marker line is
   unambiguous.

Isolation and limits
--------------------
* ``timeout_seconds`` bounds each individual check, enforced with
  ``signal.setitimer(signal.ITIMER_REAL, ...)`` plus a ``SIGALRM`` handler. The
  outstanding timer and handler are captured and restored around every check so
  deadlines nest instead of corrupting one another.
* ``DeadlineExceeded`` derives from ``BaseException`` because student code
  routinely wraps experiments in ``except Exception``. Code that goes further and
  swallows ``BaseException`` in a loop gets a second alarm one second later; on
  that second alarm the grader stops trying to unwind, records the remaining
  checks as failed and exits. A missed deadline therefore never becomes an
  infinite run.
* A total wall-clock budget covers the whole evaluation (the notebook run and all
  checks). Each check's budget is clamped to whatever remains, and once the total
  budget is gone the remaining checks are recorded as failed without being run.
* This module intentionally imports nothing from the scientific stack. pandas and
  matplotlib are imported only by the notebook under test, with ``MPLBACKEND=Agg``
  set by the container so ``plt.show()`` is a harmless no-op.

Output channel
--------------
The result line is written to a private duplicate of the process' original stdout
file descriptor, and fd 1 is then pointed at stderr. Notebook code can therefore
print freely, or even rebind ``sys.stdout``, without being able to interleave
anything into the result line.

Notebook accommodations
-----------------------
Line magics (``%matplotlib inline``) and shell escapes (``!pip install ...``) are
not Python and cannot be compiled, yet JupyterLab writes them into ordinary
notebooks, so full-line magics are replaced by a ``pass`` statement at the same
indentation (line numbering is preserved). A cell whose first non-blank line is a
``%%`` cell magic is skipped with a note on stderr, because its body is not
necessarily Python. Both accommodations apply only to the notebook run, never to
the assertion checks.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from typing import Any

RESULT_MARKER = "###OPENCE_RESULT###"

#: Subdirectory of the staging root that notebook-relative paths resolve in.
WORK_SUBDIR = "work"

#: Longest failure description kept per check.
MAX_MESSAGE_CHARS = 500

#: Longest sanitised traceback tail kept in the top-level error.
MAX_TRACEBACK_CHARS = 1200

#: Used when ``checks.json`` omits or mis-specifies ``timeout_seconds``.
DEFAULT_TEST_TIMEOUT_SECONDS = 60

#: Hard ceiling on the total budget, whatever the checks claim.
MAX_TOTAL_SECONDS = 1800

#: Grace period before giving up on code that swallowed the deadline exception.
BACKUP_ALARM_SECONDS = 1.0

#: Placeholder substituted for container paths in every reported message.
PATH_PLACEHOLDER = "<work>"

TRACEBACK_MARKER = "--- traceback (tail) ---"

_HAS_ITIMER = hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")

#: Duplicate of the real stdout, held for the single result line.
_RESULT_FD: int | None = None

#: Progress recorded so that even an abrupt termination reports something useful.
_PROGRESS: dict[str, Any] = {
    "tests": [],
    "results": [],
    "current": None,
}


def _log(message: str) -> None:
    """Human-readable progress on stderr; never touches the result channel."""
    try:
        print(f"[grade_runner] {message}", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - stderr may be closed or replaced
        pass


class DeadlineExceeded(BaseException):
    """Raised by the SIGALRM handler when a deadline expires.

    Derived from ``BaseException`` on purpose: student code routinely writes
    ``except Exception`` around its own experiments, and a check that has run out
    of time must stop the check rather than being silently swallowed.
    """

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.label = label


class GradeInputError(Exception):
    """The staged JSON documents are missing or malformed."""


# --------------------------------------------------------------------------- #
# Deadlines
# --------------------------------------------------------------------------- #
def _abort(label: str) -> None:
    """Give up on an uninterruptible check, report it, and exit.

    Called from the signal handler's second firing. Only does trivial work: the
    interpreter is in an unknown state, so no new imports, no buffered I/O and no
    exception propagation.
    """
    results = list(_PROGRESS["results"])
    tests = _PROGRESS["tests"]
    current = _PROGRESS["current"]
    for index, test in enumerate(tests):
        test_id, description = _test_identity(test, index)
        if any(result.get("id") == test_id for result in results):
            continue
        results.append(
            {
                "id": test_id,
                "description": description,
                "passed": False,
                "message": (
                    f"{label} (the interrupt was swallowed)"
                    if test_id == current
                    else "not run: the evaluation was aborted"
                ),
            }
        )
    passed_count = sum(1 for result in results if result.get("passed"))
    payload = {
        "passed": False,
        "score": round(passed_count / len(results), 3) if results else 0.0,
        "tests": results,
        "error": f"evaluation aborted: {label}",
    }
    try:
        _write_result_line(payload)
    finally:
        os._exit(1)  # noqa: SLF001 - normal interpreter shutdown is not safe here


class _Deadline:
    """Bound a block of code with ``signal.setitimer(signal.ITIMER_REAL, ...)``.

    Nesting is safe: the previous handler and the outstanding timer's remaining
    time are captured and restored on exit, so an inner deadline does not cancel
    an outer one.

    ``fired`` tells the caller whether the alarm went off, which is how a check
    that caught ``BaseException`` and returned normally is still recorded as a
    failure rather than a pass.
    """

    def __init__(self, seconds: float | None, label: str) -> None:
        self.seconds = seconds
        self.label = label
        self.fired = False
        self._active = _HAS_ITIMER and seconds is not None and seconds > 0
        self._previous_handler: Any = None
        self._previous_timer: tuple[float, float] = (0.0, 0.0)

    def __enter__(self) -> "_Deadline":
        if not self._active:
            return self

        def _on_alarm(signum, frame):  # noqa: ANN001 - signal handler signature
            if not self.fired:
                self.fired = True
                # Re-arm before raising: if the exception below is swallowed by
                # an ``except BaseException`` loop, control still comes back.
                signal.setitimer(signal.ITIMER_REAL, BACKUP_ALARM_SECONDS)
                raise DeadlineExceeded(self.label)
            _abort(self.label)

        self._previous_handler = signal.getsignal(signal.SIGALRM)
        self._previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.setitimer(signal.ITIMER_REAL, float(self.seconds))
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001 - context protocol
        if not self._active:
            return False
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._previous_handler)
        remaining, interval = self._previous_timer
        if remaining > 0:
            try:
                signal.setitimer(signal.ITIMER_REAL, remaining, interval)
            except (ValueError, OSError):  # pragma: no cover - defensive
                pass
        return False


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _sanitize(text: str, absolute_roots: list[str]) -> str:
    """Strip absolute paths so a result never leaks the host filesystem layout."""
    if not text:
        return ""
    for root in sorted({root for root in absolute_roots if root}, key=len, reverse=True):
        text = text.replace(root, PATH_PLACEHOLDER)
    return text


def _describe_exception(exc: BaseException) -> str:
    """A compact, single-line description of a raised exception."""
    name = type(exc).__name__
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - exotic __str__ implementations
        text = ""
    return f"{name}: {text}" if text else name


def _traceback_tail(exc: BaseException, roots: list[str]) -> str:
    """The last few frames of a traceback, sanitised and bounded.

    The grader's own frames are omitted: they describe the harness, not the
    student's mistake, and their paths would be the only host paths left.
    """
    own_file = os.path.abspath(__file__)
    try:
        frames = traceback.extract_tb(exc.__traceback__)
        student_frames = [frame for frame in frames if frame.filename != own_file]
        formatted = list(traceback.format_exception_only(type(exc), exc))
        if student_frames:
            formatted = (
                ["Traceback (most recent call last):\n"]
                + traceback.format_list(student_frames[-6:])
                + formatted
            )
    except Exception:  # noqa: BLE001 - defensive
        return ""
    lines = [line.strip() for line in "".join(formatted).strip().splitlines() if line.strip()]
    return _truncate(_sanitize("\n".join(lines[-8:]), roots), MAX_TRACEBACK_CHARS)


# --------------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------------- #
def _read_json(path: str, what: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise GradeInputError(f"{what} is missing") from exc
    except IsADirectoryError as exc:
        raise GradeInputError(f"{what} is not a file") from exc
    except UnicodeDecodeError as exc:
        raise GradeInputError(f"{what} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise GradeInputError(f"{what} is not valid JSON (line {exc.lineno})") from exc
    except OSError as exc:
        raise GradeInputError(f"{what} could not be read ({type(exc).__name__})") from exc
    except ValueError as exc:  # e.g. an invalid top-level document
        raise GradeInputError(f"{what} is not valid JSON ({exc})") from exc


def _cell_source(cell: dict[str, Any]) -> str:
    """A cell ``source`` is either a string or a list of strings."""
    source = cell.get("source", "")
    if source is None:
        return ""
    if isinstance(source, str):
        return source
    if isinstance(source, (list, tuple)):
        return "".join(part if isinstance(part, str) else str(part) for part in source)
    return str(source)


def _is_line_magic(line: str) -> bool:
    stripped = line.lstrip()
    # ``%matplotlib inline`` and ``!pip install x``. Inline magics such as
    # ``x = %time f()`` are not rewritten and will fail loudly instead of being
    # silently altered.
    return stripped.startswith(("%", "!"))


def _prepare_cell_source(source: str) -> str:
    """Return compilable Python for one notebook cell.

    An empty string means the body is not Python at all (a ``%%`` cell magic)
    and must be skipped. Full-line magics become ``pass`` rather than being
    deleted, so a syntax error still points at the same line of the cell.
    """
    lines = source.splitlines()
    for line in lines:
        if not line.strip():
            continue
        if line.lstrip().startswith("%%"):
            return ""
        break
    if not any(_is_line_magic(line) for line in lines):
        return source
    rewritten = []
    for line in lines:
        if _is_line_magic(line):
            indent = line[: len(line) - len(line.lstrip())]
            rewritten.append(f"{indent}pass  # grade_runner: notebook magic removed")
        else:
            rewritten.append(line)
    return "\n".join(rewritten)


def _timeout_from(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


def _test_identity(test: Any, index: int) -> tuple[str, str]:
    """Best-effort ``(id, description)`` for a configured check."""
    test_id = f"test-{index + 1}"
    description = ""
    if isinstance(test, dict):
        raw_id = test.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            test_id = raw_id
        raw_description = test.get("description")
        if isinstance(raw_description, str):
            description = raw_description
    return test_id, description


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def _execute_code(code: str, filename: str, namespace: dict[str, Any]) -> None:
    """Compile and run one snippet against the shared namespace."""
    exec(compile(code, filename, "exec"), namespace)  # noqa: S102 - by design


def _execute_notebook(
    notebook: Any,
    namespace: dict[str, Any],
    deadline_at: float,
    label: str,
) -> int:
    """Run every code cell in order. Returns how many cells actually ran."""
    if not isinstance(notebook, dict):
        raise GradeInputError("notebook.json is not a notebook document")
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise GradeInputError("notebook.json has no 'cells' list")

    executed = 0
    with _Deadline(deadline_at - time.monotonic(), label):
        for index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                _log(f"cell {index}: not a JSON object, skipped")
                continue
            if cell.get("cell_type") != "code":
                continue
            raw = _cell_source(cell)
            if not raw.strip():
                continue
            code = _prepare_cell_source(raw)
            if not code.strip():
                _log(f"cell {index}: skipped (non-Python cell magic)")
                continue
            _log(f"cell {index}: executing")
            # A synthetic, non-absolute filename keeps syntax errors and
            # tracebacks free of the staging directory layout.
            _execute_code(code, f"<notebook cell {index}>", namespace)
            executed += 1
    return executed


def _run_checks(
    tests: list[Any],
    namespace: dict[str, Any],
    per_test_timeout: float,
    deadline_at: float,
    roots: list[str],
) -> list[dict[str, Any]]:
    """Execute each check; a check passes when its exec raises nothing."""
    results: list[dict[str, Any]] = []

    for index, test in enumerate(tests):
        test_id, description = _test_identity(test, index)
        code = ""
        if isinstance(test, dict):
            raw_code = test.get("code")
            if isinstance(raw_code, str):
                code = raw_code

        if not code.strip():
            _log(f"check {test_id}: no code, counted as failed")
            results.append(
                {
                    "id": test_id,
                    "description": description,
                    "passed": False,
                    "message": "check has no code",
                }
            )
            continue

        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            _log(f"check {test_id}: total budget exhausted, not run")
            results.append(
                {
                    "id": test_id,
                    "description": description,
                    "passed": False,
                    "message": "not run: the evaluation time budget was exhausted",
                }
            )
            continue

        budget = min(per_test_timeout, remaining)
        label = f"check '{test_id}' exceeded its {budget:.3g}s time limit"
        _log(f"check {test_id}: executing (budget {budget:.3g}s)")
        _PROGRESS["current"] = test_id
        _PROGRESS["results"] = results
        guard = _Deadline(budget, label)
        try:
            with guard:
                _execute_code(code, f"<check {test_id}>", namespace)
        except DeadlineExceeded as exc:
            message = _truncate(_sanitize(exc.label, roots), MAX_MESSAGE_CHARS)
            _log(f"check {test_id}: FAILED - {message}")
            results.append(
                {
                    "id": test_id,
                    "description": description,
                    "passed": False,
                    "message": message,
                }
            )
        except BaseException as exc:  # noqa: BLE001 - student code: any failure fails
            message = _truncate(
                _sanitize(_describe_exception(exc), roots), MAX_MESSAGE_CHARS
            )
            if guard.fired:
                # The check caught the deadline and turned it into a different
                # exception; report the timeout, which is the real problem.
                message = _truncate(_sanitize(label, roots), MAX_MESSAGE_CHARS)
            _log(f"check {test_id}: FAILED - {message}")
            results.append(
                {
                    "id": test_id,
                    "description": description,
                    "passed": False,
                    "message": message,
                }
            )
        else:
            # A check that swallowed the deadline signal and then returned
            # normally must not be able to claim a pass.
            if guard.fired:
                message = _truncate(_sanitize(label, roots), MAX_MESSAGE_CHARS)
                _log(f"check {test_id}: FAILED - {message} (interrupt swallowed)")
                results.append(
                    {
                        "id": test_id,
                        "description": description,
                        "passed": False,
                        "message": message,
                    }
                )
            else:
                _log(f"check {test_id}: passed")
                results.append(
                    {
                        "id": test_id,
                        "description": description,
                        "passed": True,
                        "message": "",
                    }
                )
        finally:
            _PROGRESS["current"] = None
            _PROGRESS["results"] = results

    return results


def _all_failed(tests: list[Any], message: str) -> list[dict[str, Any]]:
    """One failed result per configured check, sharing a single explanation."""
    results = []
    for index, test in enumerate(tests):
        test_id, description = _test_identity(test, index)
        results.append(
            {
                "id": test_id,
                "description": description,
                "passed": False,
                "message": message,
            }
        )
    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def evaluate(root: str) -> dict[str, Any]:
    """Grade one submission. Always returns a result document."""
    absolute_root = os.path.abspath(root)
    workdir = os.path.join(absolute_root, WORK_SUBDIR)
    roots = [absolute_root, root, workdir, os.path.dirname(os.path.abspath(__file__))]

    # --- stage inputs ----------------------------------------------------
    try:
        notebook = _read_json(os.path.join(absolute_root, "notebook.json"), "notebook.json")
        checks = _read_json(os.path.join(absolute_root, "checks.json"), "checks.json")
    except GradeInputError as exc:
        _log(f"cannot grade: {exc}")
        return {"passed": False, "score": 0.0, "tests": [], "error": str(exc)}

    if not isinstance(checks, dict):
        error = "checks.json is not a JSON object"
        _log(f"cannot grade: {error}")
        return {"passed": False, "score": 0.0, "tests": [], "error": error}

    raw_tests: Any = checks.get("tests")
    if raw_tests is None:
        raw_tests = []
    if not isinstance(raw_tests, list):
        error = "checks.json 'tests' is not a list"
        _log(f"cannot grade: {error}")
        return {"passed": False, "score": 0.0, "tests": [], "error": error}
    tests: list[Any] = raw_tests

    if not tests:
        _log("cannot grade: no tests configured")
        return {"passed": False, "score": 0.0, "tests": [], "error": "no tests configured"}

    per_test_timeout = _timeout_from(checks.get("timeout_seconds"))
    if per_test_timeout is None:
        per_test_timeout = float(DEFAULT_TEST_TIMEOUT_SECONDS)
        _log(
            "checks.json has no usable 'timeout_seconds'; "
            f"using {DEFAULT_TEST_TIMEOUT_SECONDS}s per check"
        )

    budget = min(MAX_TOTAL_SECONDS, per_test_timeout * (len(tests) + 2) + 15.0)
    deadline_at = time.monotonic() + budget
    _PROGRESS["tests"] = tests
    _PROGRESS["results"] = []
    _PROGRESS["current"] = None
    _log(
        f"grading {len(tests)} check(s): {per_test_timeout:g}s each, "
        f"{budget:g}s total budget"
    )

    # --- working directory ------------------------------------------------
    try:
        os.makedirs(workdir, exist_ok=True)
    except OSError as exc:
        error = f"could not create the working directory ({type(exc).__name__})"
        _log(f"cannot grade: {error}")
        return {
            "passed": False,
            "score": 0.0,
            "tests": _all_failed(tests, "not evaluated: no working directory"),
            "error": error,
        }
    try:
        os.chdir(workdir)
    except OSError as exc:
        error = f"could not enter the working directory ({type(exc).__name__})"
        _log(f"cannot grade: {error}")
        return {
            "passed": False,
            "score": 0.0,
            "tests": _all_failed(tests, "not evaluated: no working directory"),
            "error": error,
        }
    _log(f"working directory: {WORK_SUBDIR}/")

    # --- shared namespace --------------------------------------------------
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__builtins__": __builtins__,
    }

    # --- notebook ----------------------------------------------------------
    notebook_label = "notebook execution exceeded the total time budget"
    _PROGRESS["current"] = "notebook"
    try:
        executed = _execute_notebook(notebook, namespace, deadline_at, notebook_label)
    except DeadlineExceeded:
        error = f"notebook execution timed out (total budget {budget:.3g}s)"
        _log(error)
        return {
            "passed": False,
            "score": 0.0,
            "tests": _all_failed(tests, "not evaluated: notebook execution timed out"),
            "error": error,
        }
    except GradeInputError as exc:
        error = str(exc)
        _log(f"cannot grade: {error}")
        return {
            "passed": False,
            "score": 0.0,
            "tests": _all_failed(tests, "not evaluated: notebook could not be read"),
            "error": error,
        }
    except BaseException as exc:  # noqa: BLE001 - student code: any failure fails
        description = _sanitize(_describe_exception(exc), roots)
        tail = _traceback_tail(exc, roots)
        error = f"notebook execution failed before the checks could run: {description}"
        if tail:
            error = f"{error}\n{TRACEBACK_MARKER}\n{tail}"
        _log(f"notebook execution failed: {description}")
        return {
            "passed": False,
            "score": 0.0,
            "tests": _all_failed(tests, "not evaluated: notebook execution failed"),
            "error": _truncate(error, MAX_TRACEBACK_CHARS + 300),
        }
    finally:
        _PROGRESS["current"] = None

    _log(f"notebook executed ({executed} code cell(s)); running checks")

    # --- checks ------------------------------------------------------------
    results = _run_checks(tests, namespace, per_test_timeout, deadline_at, roots)
    passed_count = sum(1 for result in results if result["passed"])
    score = round(passed_count / len(results), 3) if results else 0.0
    _log(f"{passed_count}/{len(results)} checks passed (score {score})")

    return {
        "passed": bool(results) and score == 1.0,
        "score": score,
        "tests": results,
        "error": None,
    }


# --------------------------------------------------------------------------- #
# Result line
# --------------------------------------------------------------------------- #
def _payload(result: dict[str, Any]) -> dict[str, Any]:
    """The exact wire shape the backend parses."""
    raw_tests = result.get("tests") or []
    return {
        "passed": bool(result.get("passed")),
        "score": round(float(result.get("score", 0.0)), 3),
        "tests": [
            {
                "id": str(item.get("id", "check")),
                "description": str(item.get("description", "")),
                "passed": bool(item.get("passed")),
                "message": str(item.get("message", "")),
            }
            for item in raw_tests
        ],
        "error": result.get("error"),
    }


def _write_result_line(result: dict[str, Any]) -> None:
    """Write the marker line to the private stdout duplicate, or to fd 1."""
    line = (
        RESULT_MARKER
        + json.dumps(_payload(result), separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    data = line.encode("utf-8")
    fd = _RESULT_FD if _RESULT_FD is not None else 1
    while data:
        written = os.write(fd, data)
        if written <= 0:  # pragma: no cover - defensive
            break
        data = data[written:]


def _claim_stdout() -> None:
    """Keep a private stdout for the result line and send everything else to stderr.

    Notebook code gets fd 1 pointing at stderr, so even C-level output or code
    that rebinds ``sys.stdout`` cannot corrupt the result channel.
    """
    global _RESULT_FD
    try:
        _RESULT_FD = os.dup(1)
    except OSError:  # pragma: no cover - stdio is broken
        _RESULT_FD = None
    try:
        os.dup2(2, 1)
    except OSError:  # pragma: no cover - defensive
        pass
    sys.stdout = sys.stderr


def main(argv: list[str]) -> int:
    root = argv[1] if len(argv) > 1 else "/work"
    _log(f"grading root argument: {root!r}")
    _claim_stdout()

    try:
        result = evaluate(root)
    except BaseException as exc:  # noqa: BLE001 - never lose the result line
        _log(f"grading aborted unexpectedly: {_describe_exception(exc)}")
        result = {
            "passed": False,
            "score": 0.0,
            "tests": [],
            "error": _truncate(
                f"the grader itself failed: {_describe_exception(exc)}", MAX_MESSAGE_CHARS
            ),
        }

    try:
        _write_result_line(result)
    except Exception as exc:  # noqa: BLE001 - stdout is unusable
        _log(f"could not write the result line: {_describe_exception(exc)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
