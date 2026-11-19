import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { AssignmentOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { ConfirmButton, errorMessage, formatDateTime } from "../../components/kit";
import { useCourse } from "./CourseShell";
import { StreamTab } from "./StreamTab";

export function visibilityBadge(a: AssignmentOut) {
  if (a.archived_at) return <Badge tone="neutral">archived</Badge>;
  if (!a.is_published) return <Badge tone="purple">draft</Badge>;
  if (!a.is_visible) return <Badge tone="amber">scheduled {formatDateTime(a.publish_at)}</Badge>;
  return <Badge tone="green">published</Badge>;
}

function studentBadge(a: AssignmentOut) {
  const mine = a.my_submission;
  if (mine?.status === "graded")
    return <Badge tone="green">returned · {mine.final_score}/{a.max_points}</Badge>;
  if (mine) return <Badge tone="accent">turned in{mine.is_late ? " (late)" : ""}</Badge>;
  if (a.due_at && new Date(a.due_at) < new Date()) return <Badge tone="red">missing</Badge>;
  return <Badge tone="amber">assigned</Badge>;
}

function groupByTopic(items: AssignmentOut[]): [string, AssignmentOut[]][] {
  const groups = new Map<string, AssignmentOut[]>();
  for (const item of items) {
    const key = item.topic?.trim() || "";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  // Untitled group first, then topics alphabetically.
  return [...groups.entries()].sort(([a], [b]) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b)));
}

export function ClassworkTab() {
  const { course, isStaff, isInstructor } = useCourse();
  const [showArchived, setShowArchived] = useState(false);
  const assignments = useAsync(
    () => api.assignments(course.id, { include_archived: isStaff && showArchived }),
    [course.id, isStaff, showArchived],
  );
  const [error, setError] = useState<string | null>(null);
  const archivedCourse = course.status === "archived";

  const items = assignments.data?.assignments ?? [];

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      assignments.reload();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="spread">
        <h2 style={{ fontSize: 17, margin: 0 }}>Assignments</h2>
        <div className="row" style={{ gap: 8 }}>
          {isStaff && (
            <label className="row small dim" style={{ gap: 6 }}>
              <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
              Show archived
            </label>
          )}
          {isInstructor && !archivedCourse && (
            <Link className="btn btn-primary" to={`/classes/${course.id}/classwork/new`}>
              + Create assignment
            </Link>
          )}
        </div>
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {assignments.loading && <Loading label="Loading classwork…" />}
      {assignments.error && <ErrorBox error={assignments.error} retry={assignments.reload} />}
      {!assignments.loading && items.length === 0 && (
        <Empty title="No assignments yet">
          {isInstructor ? "Create the first assignment for this class." : "Assignments from your teacher will appear here."}
        </Empty>
      )}

      {groupByTopic(items).map(([topic, group]) => (
        <section key={topic || "_"} className="stack-sm">
          {topic && <h3 className="topic-heading">{topic}</h3>}
          <div className="card" style={{ padding: 0 }}>
            {group.map((a) => (
              <div key={a.id} className="work-row">
                <Link to={`/classes/${course.id}/classwork/${a.id}`} className="work-main">
                  <span className="work-title">{a.title}</span>
                  <span className="small dim">
                    {a.due_at ? `Due ${formatDateTime(a.due_at)}` : "No due date"} · {a.max_points} pts
                    {isStaff && a.submission_count !== null && ` · ${a.submission_count} turned in`}
                  </span>
                </Link>
                <div className="row" style={{ gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {isStaff ? visibilityBadge(a) : studentBadge(a)}
                  {isStaff && (
                    <Link className="btn btn-sm btn-primary" to={`/grade/${a.id}`}>
                      Grade
                    </Link>
                  )}
                  {isInstructor && !archivedCourse && (
                    <>
                      <Link className="btn btn-sm" to={`/classes/${course.id}/classwork/${a.id}/edit`}>
                        Edit
                      </Link>
                      {a.archived_at ? (
                        <button className="btn btn-sm" type="button" onClick={() => run(() => api.archiveAssignment(a.id, false))}>
                          Restore
                        </button>
                      ) : a.submission_count ? (
                        <ConfirmButton label="Archive" confirmLabel="Archive" onConfirm={() => run(() => api.archiveAssignment(a.id, true))} />
                      ) : (
                        <ConfirmButton label="Delete" confirmLabel="Delete" danger onConfirm={() => run(() => api.deleteAssignment(a.id))} />
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      <div style={{ marginTop: 10 }}>
        <h2 style={{ fontSize: 17, margin: "0 0 10px" }}>Materials &amp; notes</h2>
        <StreamTab kind="material" />
      </div>
    </div>
  );
}
