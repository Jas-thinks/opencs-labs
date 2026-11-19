import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { formatDateTime } from "../../components/kit";

/** Everything waiting for grading or return, across all classes I teach. */
export function ToGradePage() {
  const queue = useAsync(() => api.gradingQueue(), []);
  if (queue.loading) return <Loading label="Loading your grading queue…" />;
  if (queue.error) return <ErrorBox error={queue.error} retry={queue.reload} />;
  const items = queue.data?.items ?? [];
  return (
    <div className="stack" style={{ gap: 18 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>To grade</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Latest submissions that are ungraded, and drafts you have not returned yet.
          </p>
        </div>
      </header>
      {items.length === 0 ? (
        <Empty title="All caught up">Nothing is waiting for grading or return.</Empty>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          {items.map((item) => (
            <Link key={item.assignment_id} to={`/grade/${item.assignment_id}`} className="work-row">
              <div className="work-main">
                <span className="work-title">{item.assignment_title}</span>
                <span className="small dim">
                  {item.course_code} · {item.due_at ? `due ${formatDateTime(item.due_at)}` : "no due date"}
                </span>
              </div>
              <div className="row" style={{ gap: 6 }}>
                {item.ungraded > 0 && <Badge tone="amber">{item.ungraded} to grade</Badge>}
                {item.late > 0 && <Badge tone="red">{item.late} late</Badge>}
                {item.drafts > 0 && <Badge tone="purple">{item.drafts} drafts to return</Badge>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
