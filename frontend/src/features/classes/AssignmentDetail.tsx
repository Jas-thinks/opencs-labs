import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { AssignmentOut, SubmissionDetailOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Prose } from "../../components/Blocks";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { errorMessage, formatDateTime } from "../../components/kit";
import { useCourse } from "./CourseShell";
import { visibilityBadge } from "./ClassworkTab";

export function AssignmentDetail() {
  const { assignmentId = "" } = useParams();
  const { isStaff } = useCourse();
  const assignment = useAsync(() => api.assignment(assignmentId), [assignmentId]);
  if (assignment.loading) return <Loading label="Loading assignment…" />;
  if (assignment.error) return <ErrorBox error={assignment.error} retry={assignment.reload} />;
  const data = assignment.data;
  if (!data) return null;
  return isStaff ? <StaffView assignment={data} /> : <StudentView assignment={data} onChanged={assignment.reload} />;
}

function Header({ assignment }: { assignment: AssignmentOut }) {
  const { course } = useCourse();
  return (
    <div className="stack-sm">
      <Link className="small dim" to={`/classes/${course.id}/classwork`}>
        ← Classwork
      </Link>
      <h1 style={{ margin: 0 }}>{assignment.title}</h1>
      <div className="row small dim" style={{ gap: 10, flexWrap: "wrap" }}>
        <span>{assignment.max_points} points</span>
        <span>{assignment.due_at ? `Due ${formatDateTime(assignment.due_at)}` : "No due date"}</span>
        {assignment.topic && <Badge tone="neutral">{assignment.topic}</Badge>}
        {!assignment.allow_late && <Badge tone="red">no late work</Badge>}
        {assignment.allow_late && assignment.late_penalty_pct > 0 && (
          <span>late penalty {assignment.late_penalty_pct}%</span>
        )}
      </div>
    </div>
  );
}

function StaffView({ assignment }: { assignment: AssignmentOut }) {
  const { course, isInstructor } = useCourse();
  return (
    <div className="stack" style={{ gap: 18, maxWidth: 900 }}>
      <Header assignment={assignment} />
      <div className="row" style={{ gap: 8 }}>
        {visibilityBadge(assignment)}
        <span className="small dim">{assignment.submission_count ?? 0} students turned in</span>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <Link className="btn btn-primary" to={`/grade/${assignment.id}`}>
          Open grading
        </Link>
        {isInstructor && (
          <Link className="btn" to={`/classes/${course.id}/classwork/${assignment.id}/edit`}>
            Edit assignment &amp; rubric
          </Link>
        )}
      </div>
      <section className="card">
        <div className="label" style={{ marginBottom: 8 }}>Instructions as students see them</div>
        {assignment.description.trim() ? <Prose text={assignment.description} /> : <span className="dim small">No instructions.</span>}
      </section>
    </div>
  );
}

function StudentView({ assignment, onChanged }: { assignment: AssignmentOut; onChanged: () => void }) {
  const notebooks = useAsync(() => api.notebooks(), []);
  const mine = assignment.my_submission;
  const returned = mine?.status === "graded";
  const detail = useAsync(
    () => (mine && returned ? api.submission(mine.id) : Promise.resolve(null)),
    [mine?.id, returned],
  );
  const source = `assignment:${assignment.id}`;
  const assignmentNotebook = (notebooks.data?.notebooks ?? []).find((n) => n.source_ref === source);
  const [notebookId, setNotebookId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!notebookId && assignmentNotebook) setNotebookId(assignmentNotebook.id);
  }, [notebookId, assignmentNotebook]);

  const overdue = assignment.due_at ? new Date(assignment.due_at) < new Date() : false;
  const closed = overdue && !assignment.allow_late;

  async function start() {
    setBusy(true);
    setError(null);
    // Open the tab inside the click (popup blockers reject window.open after
    // an await), then point it at the notebook once the copy exists.
    const tab = window.open("about:blank", "_blank");
    try {
      const result = await api.startAssignment(assignment.id);
      notebooks.reload();
      setNotebookId(result.notebook_id);
      if (tab) {
        tab.opener = null;
        tab.location.href = result.url;
      } else {
        window.location.href = result.url;
      }
    } catch (cause) {
      tab?.close();
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function turnIn() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const submission = await api.submitAssignment(assignment.id, notebookId);
      setMessage(`Turned in (attempt ${submission.attempt_number}${submission.is_late ? ", late" : ""}). Your teacher sees this exact snapshot.`);
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 18, maxWidth: 900 }}>
      <Header assignment={assignment} />
      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="card">
          <div className="label" style={{ marginBottom: 8 }}>Instructions</div>
          {assignment.description.trim() ? <Prose text={assignment.description} /> : <span className="dim small">No instructions.</span>}
        </section>
        <section className="card stack">
          <div className="spread">
            <span className="label">Your work</span>
            {mine ? (
              returned ? (
                <Badge tone="green">returned · {mine.final_score}/{assignment.max_points}</Badge>
              ) : (
                <Badge tone="accent">turned in{mine.is_late ? " (late)" : ""}</Badge>
              )
            ) : overdue ? (
              <Badge tone="red">missing</Badge>
            ) : (
              <Badge tone="amber">assigned</Badge>
            )}
          </div>
          <button className="btn" type="button" onClick={start} disabled={busy}>
            {assignmentNotebook ? "Open my notebook" : assignment.has_starter ? "Start assignment (copy starter)" : "Start assignment"}
          </button>
          <label className="field">
            <span className="label">Notebook to turn in</span>
            <select className="select" value={notebookId} onChange={(e) => setNotebookId(e.target.value)}>
              <option value="">Choose a notebook…</option>
              {(notebooks.data?.notebooks ?? []).map((n) => (
                <option key={n.id} value={n.id}>
                  {n.title}
                  {n.source_ref === source ? " (this assignment)" : ""}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" type="button" onClick={turnIn} disabled={busy || !notebookId || closed}>
            {mine ? "Turn in again" : "Turn in"}
          </button>
          {closed && <span className="small dim">The due date has passed and late work is not accepted.</span>}
          {mine && !closed && <span className="small dim">You can turn in again until the due date; your teacher grades the latest attempt.</span>}
          {message && <div className="notice notice-success">{message}</div>}
          {error && <div className="notice notice-error">{error}</div>}
        </section>
      </div>
      {detail.data && <Feedback detail={detail.data} />}
    </div>
  );
}

export function Feedback({ detail }: { detail: SubmissionDetailOut }) {
  const grade = detail.latest_grade;
  if (!grade) return null;
  return (
    <section className="card stack">
      <div className="spread">
        <h2 style={{ fontSize: 16, margin: 0 }}>Feedback</h2>
        <strong>
          {detail.final_score} / {detail.max_points}
        </strong>
      </div>
      {grade.criteria.map((c) => (
        <div key={c.criterion_id} className="feedback-row">
          <div className="spread">
            <span style={{ fontWeight: 600 }}>{c.label}</span>
            <span>
              {c.points} / {c.max_points}
            </span>
          </div>
          {c.comment && <div className="small">{c.comment}</div>}
        </div>
      ))}
      {grade.feedback.trim() && (
        <div>
          <div className="label">Overall</div>
          <Prose text={grade.feedback} />
        </div>
      )}
      <span className="small dim">Returned {formatDateTime(grade.released_at ?? grade.published_at)} · revision {grade.revision}</span>
    </section>
  );
}
