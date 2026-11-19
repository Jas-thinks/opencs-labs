import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { GradebookCell } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { formatDateTime } from "../../components/kit";
import { useCourse } from "./CourseShell";
import { Feedback } from "./AssignmentDetail";
import { TeachingPage } from "../grading/TeachingPage";

export function GradesTab() {
  const { isStaff } = useCourse();
  return isStaff ? <Gradebook /> : <MyGrades />;
}

export function InsightsTab() {
  const { course } = useCourse();
  return <TeachingPage courseId={course.id} />;
}

function cellView(cell: GradebookCell, max: number) {
  switch (cell.state) {
    case "returned":
      return <span className={cell.is_late ? "gb-late" : undefined}>{cell.score}<span className="dim">/{max}</span></span>;
    case "draft":
      return <Badge tone="purple">draft</Badge>;
    case "submitted":
      return <Badge tone="amber">to grade</Badge>;
    case "missing":
      return <span style={{ color: "var(--red)" }}>missing</span>;
    default:
      return <span className="dim">—</span>;
  }
}

function Gradebook() {
  const { course } = useCourse();
  const book = useAsync(() => api.gradebook(course.id), [course.id]);
  if (book.loading) return <Loading label="Loading gradebook…" />;
  if (book.error) return <ErrorBox error={book.error} retry={book.reload} />;
  const data = book.data;
  if (!data || data.assignments.length === 0) {
    return <Empty title="No published assignments">The gradebook fills in as you publish and grade work.</Empty>;
  }
  return (
    <div className="stack">
      <div className="spread">
        <span className="small dim">Scores show returned grades. Weighted % counts returned work only, using each assignment&apos;s weight.</span>
        <a className="btn btn-ghost btn-sm" href={api.courseExportUrl(course.id)}>
          Export CSV
        </a>
      </div>
      <div className="table-wrap gradebook">
        <table className="data">
          <thead>
            <tr>
              <th className="gb-sticky">Student</th>
              <th>Weighted</th>
              {data.assignments.map((a) => (
                <th key={a.id} title={`${a.max_points} pts · weight ${a.weight}`}>
                  <Link to={`/grade/${a.id}`}>{a.title}</Link>
                  <div className="small dim">{a.due_at ? formatDateTime(a.due_at) : "no due date"}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.user_id}>
                <td className="gb-sticky">
                  <Link to={`/teaching/courses/${course.id}/students/${row.user_id}`}>{row.display_name}</Link>
                </td>
                <td>
                  <strong>{row.weighted_percent === null ? "—" : `${row.weighted_percent}%`}</strong>
                </td>
                {row.cells.map((cell, i) => (
                  <td key={cell.assignment_id}>
                    {cell.submission_id ? (
                      <Link to={`/grade/${cell.assignment_id}?s=${cell.submission_id}`}>
                        {cellView(cell, data.assignments[i].max_points)}
                      </Link>
                    ) : (
                      cellView(cell, data.assignments[i].max_points)
                    )}
                  </td>
                ))}
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={data.assignments.length + 2}>No students enrolled yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MyGrades() {
  const { course } = useCourse();
  const grades = useAsync(() => api.myGrades(course.id), [course.id]);
  const [open, setOpen] = useState<string | null>(null);
  const detail = useAsync(() => (open ? api.submission(open) : Promise.resolve(null)), [open]);
  if (grades.loading) return <Loading label="Loading grades…" />;
  if (grades.error) return <ErrorBox error={grades.error} retry={grades.reload} />;
  const rows = grades.data?.grades ?? [];
  if (rows.length === 0) {
    return <Empty title="No returned work yet">Grades appear here once your teacher returns them.</Empty>;
  }
  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="card" style={{ padding: 0 }}>
        {rows.map((g) => (
          <div key={g.submission_id}>
            <button type="button" className="work-row work-row-button" onClick={() => setOpen(open === g.submission_id ? null : g.submission_id)}>
              <div className="work-main">
                <span className="work-title">{g.assignment_title}</span>
                <span className="small dim">
                  Returned {formatDateTime(g.published_at)} · attempt {g.attempt_number}
                  {g.is_late ? " · late" : ""}
                </span>
              </div>
              <strong>
                {g.final_score ?? "—"} / {g.max_points}
              </strong>
            </button>
            {open === g.submission_id && (
              <div style={{ padding: "0 16px 16px" }}>
                {detail.loading && <Loading label="Loading feedback…" />}
                {detail.data && <Feedback detail={detail.data} />}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
