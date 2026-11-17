import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { StudentDashboard } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  Progress,
  formatDate,
  formatNumber,
} from "../../components/ui";

function formatDuration(seconds: number): string {
  if (!seconds) return "0m";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function statusTone(status: string): "green" | "amber" | "neutral" | "red" {
  if (status === "graded") return "green";
  if (status === "submitted") return "amber";
  if (status === "returned") return "red";
  return "neutral";
}

function SubmitWork({ courseId }: { courseId: string }) {
  const assignments = useAsync(() => api.assignments(courseId), [courseId]);
  const notebooks = useAsync(() => api.notebooks(), []);
  const [assignmentId, setAssignmentId] = useState("");
  const [notebookId, setNotebookId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!assignmentId || !notebookId) {
      setError(new Error("Choose an assignment and a notebook first."));
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const submission = await api.submitAssignment(assignmentId, notebookId);
      setMessage(
        `Submitted attempt ${submission.attempt_number}${submission.is_late ? " (late)" : ""}.`,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (!assignments.data || assignments.data.assignments.length === 0) return null;

  return (
    <section className="card stack">
      <div>
        <h2 style={{ fontSize: 16, marginBottom: 4 }}>Submit work</h2>
        <p className="small dim" style={{ margin: 0 }}>
          A submission snapshots the current notebook immutably. You can resubmit until the due
          date.
        </p>
      </div>
      <div className="grid grid-2">
        <label className="field">
          <span className="label">Assignment</span>
          <select className="select" value={assignmentId} onChange={(e) => setAssignmentId(e.target.value)}>
            <option value="">Select an assignment…</option>
            {assignments.data.assignments.map((assignment) => (
              <option key={assignment.id} value={assignment.id}>
                {assignment.title}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Notebook</span>
          <select className="select" value={notebookId} onChange={(e) => setNotebookId(e.target.value)}>
            <option value="">Select a notebook…</option>
            {(notebooks.data?.notebooks ?? []).map((notebook) => (
              <option key={notebook.id} value={notebook.id}>
                {notebook.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <button className="btn btn-primary" type="button" onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : "Submit notebook"}
        </button>
        {message && <Badge tone="green">{message}</Badge>}
      </div>
      {error && <ErrorBox error={error} />}
    </section>
  );
}

export function DashboardPage() {
  const courses = useAsync(() => api.courses(), []);
  const [courseId, setCourseId] = useState("");

  useEffect(() => {
    if (!courseId && courses.data?.courses.length) {
      setCourseId(courses.data.courses[0].id);
    }
  }, [courseId, courses.data]);

  const dashboard = useAsync(
    () => api.myDashboard(courseId || undefined),
    [courseId],
  );
  const grades = useAsync(() => api.myGrades(courseId || undefined), [courseId]);

  if (courses.loading) return <Loading label="Loading your courses…" />;
  if (courses.error) return <ErrorBox error={courses.error} retry={courses.reload} />;

  const course = courses.data?.courses.find((item) => item.id === courseId);
  const data: StudentDashboard | null = dashboard.data;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 680 }}>
          <h1>Dashboard</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Your completion, scores, rubric mastery and time on task for a course.
          </p>
        </div>
        <select
          className="select"
          style={{ maxWidth: 320 }}
          value={courseId}
          onChange={(event) => setCourseId(event.target.value)}
        >
          {(courses.data?.courses ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.code} — {item.name}
            </option>
          ))}
        </select>
      </header>

      {dashboard.loading && <Loading label="Loading dashboard…" />}
      {dashboard.error && <ErrorBox error={dashboard.error} retry={dashboard.reload} />}

      {data && !data.course_id && (
        <Empty title="No course yet">You are not enrolled in a course.</Empty>
      )}

      {data && data.course_id && (
        <>
          <div className="grid grid-3">
            <div className="card kpi">
              <span className="kpi-label">Assignments submitted</span>
              <span className="kpi-value">
                {data.completion.submitted}
                <span className="small dim" style={{ fontWeight: 500 }}>
                  {" "}/ {data.completion.assigned}
                </span>
              </span>
              <Progress
                percent={
                  data.completion.assigned
                    ? Math.round((data.completion.submitted / data.completion.assigned) * 100)
                    : 0
                }
              />
            </div>
            <div className="card kpi">
              <span className="kpi-label">Average score</span>
              <span className="kpi-value">{data.scores.average ?? "—"}</span>
              <span className="small dim">Best {data.scores.best ?? "—"}</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Time on task</span>
              <span className="kpi-value">{formatDuration(data.time_on_task_seconds)}</span>
              <span className="small dim">
                {data.late_count} late · {data.ungraded_count} ungraded
              </span>
            </div>
          </div>

          <section className="card">
            <div className="spread" style={{ marginBottom: 10 }}>
              <h2 style={{ fontSize: 16 }}>Assignments</h2>
              {course && <Badge tone="neutral">{course.term}</Badge>}
            </div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Assignment</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Max</th>
                    <th>Due</th>
                  </tr>
                </thead>
                <tbody>
                  {data.assignments.map((assignment) => (
                    <tr key={assignment.id}>
                      <td>{assignment.title}</td>
                      <td>
                        <Badge tone={statusTone(assignment.status)}>{assignment.status}</Badge>
                        {assignment.is_late && <Badge tone="red">late</Badge>}
                      </td>
                      <td>{assignment.final_score ?? "—"}</td>
                      <td>{formatNumber(assignment.max_points)}</td>
                      <td>{formatDate(assignment.due_at)}</td>
                    </tr>
                  ))}
                  {data.assignments.length === 0 && (
                    <tr>
                      <td colSpan={5}>No published assignments yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid grid-2">
            <section className="card stack">
              <h2 style={{ fontSize: 16 }}>Rubric mastery</h2>
              {data.criteria.length === 0 && <span className="small dim">No graded rubric work yet.</span>}
              {data.criteria.map((criterion) => (
                <div key={criterion.key} className="stack-sm">
                  <div className="spread">
                    <span className="small" style={{ fontWeight: 600 }}>
                      {criterion.label}
                    </span>
                    <span className="small dim">
                      {criterion.earned}/{criterion.max} ({criterion.percent ?? 0}%)
                    </span>
                  </div>
                  <Progress percent={criterion.percent ?? 0} />
                </div>
              ))}
            </section>

            <section className="card stack">
              <h2 style={{ fontSize: 16 }}>Score trend</h2>
              {data.scores.trend.length === 0 && <span className="small dim">No scores yet.</span>}
              {data.scores.trend.map((item) => (
                <div key={item.assignment_id} className="spread">
                  <span className="small">{item.title}</span>
                  <span className="row" style={{ gap: 8 }}>
                    <span className="small dim">{formatDate(item.date)}</span>
                    <Badge tone="accent">{item.score ?? "—"}</Badge>
                  </span>
                </div>
              ))}
            </section>
          </div>

          <SubmitWork courseId={courseId} />

          <section className="card">
            <h2 style={{ fontSize: 16, marginBottom: 10 }}>Published grades</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Assignment</th>
                    <th>Attempt</th>
                    <th>Score</th>
                    <th>Late</th>
                    <th>Published</th>
                    <th>Revision</th>
                  </tr>
                </thead>
                <tbody>
                  {(grades.data?.grades ?? []).map((grade) => (
                    <tr key={`${grade.submission_id}-${grade.assignment_id}`}>
                      <td>{grade.assignment_title}</td>
                      <td>{grade.attempt_number}</td>
                      <td>
                        {grade.final_score ?? "—"} / {grade.max_points}
                      </td>
                      <td>{grade.is_late ? "yes" : "no"}</td>
                      <td>{formatDate(grade.published_at)}</td>
                      <td>{grade.revision ?? "—"}</td>
                    </tr>
                  ))}
                  {(grades.data?.grades ?? []).length === 0 && (
                    <tr>
                      <td colSpan={6}>No published grades yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
