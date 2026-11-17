import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading, Progress, formatDate } from "../../components/ui";

const STAFF_ROLES = new Set(["ta", "instructor", "admin", "staff"]);

export function TeachingPage() {
  const courses = useAsync(() => api.courses(), []);
  const staffCourses = (courses.data?.courses ?? []).filter((course) =>
    STAFF_ROLES.has(course.role_in_course),
  );
  const [courseId, setCourseId] = useState("");

  useEffect(() => {
    if (!courseId && staffCourses.length) {
      setCourseId(staffCourses[0].id);
    }
  }, [courseId, staffCourses]);

  const dashboard = useAsync(
    () => (courseId ? api.courseDashboard(courseId, { limit: 100 }) : Promise.resolve(null)),
    [courseId],
  );

  if (courses.loading) return <Loading label="Loading courses…" />;
  if (courses.error) return <ErrorBox error={courses.error} retry={courses.reload} />;
  if (staffCourses.length === 0) {
    return (
      <Empty title="Teaching access required">
        You are not course staff in any course. Ask the instructor to enroll you as a TA.
      </Empty>
    );
  }

  const data = dashboard.data;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 680 }}>
          <h1>Teaching</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Class completion, score distribution, rubric averages and the grading roster.
          </p>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <select
            className="select"
            style={{ minWidth: 280 }}
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
          >
            {staffCourses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.code} — {course.name}
              </option>
            ))}
          </select>
          {courseId && (
            <a className="btn btn-ghost btn-sm" href={api.courseExportUrl(courseId)}>
              Export CSV
            </a>
          )}
        </div>
      </header>

      {dashboard.loading && <Loading label="Loading class analytics…" />}
      {dashboard.error && <ErrorBox error={dashboard.error} retry={dashboard.reload} />}

      {data && (
        <>
          <div className="grid grid-3">
            <div className="card kpi">
              <span className="kpi-label">Students</span>
              <span className="kpi-value">{data.summary.students}</span>
              <span className="small dim">Completion {Math.round(data.summary.completion_rate * 100)}%</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Class average</span>
              <span className="kpi-value">{data.summary.average_score ?? "—"}</span>
              <span className="small dim">Late rate {Math.round(data.summary.late_rate * 100)}%</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Ungraded queue</span>
              <span className="kpi-value">{data.summary.ungraded}</span>
              <span className="small dim">Latest submissions waiting</span>
            </div>
          </div>

          <section className="card">
            <h2 style={{ fontSize: 16, marginBottom: 10 }}>Assignments</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Assignment</th>
                    <th>Submitted</th>
                    <th>Graded</th>
                    <th>Average</th>
                    <th>Distribution</th>
                    <th>Due</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.assignments.map((assignment) => (
                    <tr key={assignment.id}>
                      <td>{assignment.title}</td>
                      <td>{assignment.submitted}</td>
                      <td>{assignment.graded}</td>
                      <td>{assignment.average_score ?? "—"}</td>
                      <td>
                        <span className="row small dim" style={{ gap: 6 }}>
                          {Object.entries(assignment.distribution).map(([bucket, count]) => (
                            <span key={bucket}>
                              {bucket}: {count}
                            </span>
                          ))}
                        </span>
                      </td>
                      <td>{formatDate(assignment.due_at)}</td>
                      <td>
                        <Link className="btn btn-sm" to={`/assignments/${assignment.id}`}>
                          Grade
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {data.assignments.length === 0 && (
                    <tr>
                      <td colSpan={7}>No published assignments.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid grid-2">
            <section className="card stack">
              <h2 style={{ fontSize: 16 }}>Criterion averages</h2>
              {data.criteria.length === 0 && <span className="small dim">No graded rubric work yet.</span>}
              {data.criteria.map((criterion) => (
                <div key={criterion.key} className="stack-sm">
                  <div className="spread">
                    <span className="small" style={{ fontWeight: 600 }}>
                      {criterion.label}
                    </span>
                    <span className="small dim">{criterion.average_percent ?? 0}%</span>
                  </div>
                  <Progress percent={criterion.average_percent ?? 0} />
                </div>
              ))}
            </section>

            <section className="card stack">
              <div className="spread">
                <h2 style={{ fontSize: 16 }}>Roster</h2>
                <span className="small dim">{data.roster_total} students</span>
              </div>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Student</th>
                      <th>Submitted</th>
                      <th>Average</th>
                      <th>Late</th>
                      <th>Ungraded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.roster.map((row) => (
                      <tr key={row.user_id}>
                        <td>
                          <Link to={`/teaching/courses/${courseId}/students/${row.user_id}`}>
                            {row.display_name}
                          </Link>
                        </td>
                        <td>
                          {row.submitted}/{row.assigned}
                        </td>
                        <td>{row.average_score ?? "—"}</td>
                        <td>{row.late_count ? <Badge tone="red">{row.late_count}</Badge> : "0"}</td>
                        <td>{row.ungraded_count ? <Badge tone="amber">{row.ungraded_count}</Badge> : "0"}</td>
                      </tr>
                    ))}
                    {data.roster.length === 0 && (
                      <tr>
                        <td colSpan={5}>No enrolled students.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
