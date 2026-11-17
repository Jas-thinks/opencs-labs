import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import {
  Badge,
  ErrorBox,
  Loading,
  Progress,
  formatDate,
} from "../../components/ui";

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function StudentDetailPage() {
  const { courseId = "", userId = "" } = useParams();
  const detail = useAsync(
    () => api.studentDrilldown(courseId, userId),
    [courseId, userId],
  );

  if (detail.loading) return <Loading label="Loading student…" />;
  if (detail.error) return <ErrorBox error={detail.error} retry={detail.reload} />;
  const data = detail.data;
  if (!data) return null;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>{data.student?.display_name ?? "Student"}</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            {data.student?.email}
          </p>
        </div>
        <Badge tone="neutral">Drill-down</Badge>
      </header>

      <div className="grid grid-3">
        <div className="card kpi">
          <span className="kpi-label">Submitted</span>
          <span className="kpi-value">
            {data.completion.submitted}
            <span className="small dim" style={{ fontWeight: 500 }}>
              {" "}/ {data.completion.assigned}
            </span>
          </span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Average score</span>
          <span className="kpi-value">{data.scores.average ?? "—"}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Time on task</span>
          <span className="kpi-value">{formatDuration(data.time_on_task_seconds)}</span>
        </div>
      </div>

      <section className="card">
        <h2 style={{ fontSize: 16, marginBottom: 10 }}>Submissions</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Assignment</th>
                <th>Attempt</th>
                <th>Status</th>
                <th>Score</th>
                <th>Late</th>
                <th>Submitted</th>
                <th>Grade revision</th>
              </tr>
            </thead>
            <tbody>
              {data.submissions.map((submission) => (
                <tr key={submission.submission_id}>
                  <td>{submission.assignment_title}</td>
                  <td>{submission.attempt_number}</td>
                  <td>
                    <Badge tone={submission.status === "graded" ? "green" : "amber"}>
                      {submission.status}
                    </Badge>
                  </td>
                  <td>
                    {submission.final_score ?? "—"} / {submission.max_points}
                  </td>
                  <td>{submission.is_late ? "yes" : "no"}</td>
                  <td>{formatDate(submission.submitted_at)}</td>
                  <td>{submission.grade_revision ?? "—"}</td>
                </tr>
              ))}
              {data.submissions.length === 0 && (
                <tr>
                  <td colSpan={7}>No submissions yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

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
    </div>
  );
}
