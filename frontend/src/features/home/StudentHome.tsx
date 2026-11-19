import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAuth } from "../../app/AuthContext";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { formatDateTime, relativeTime } from "../../components/kit";

/** Student landing page: what is due, what is new, what came back. One API call. */
export function StudentHome() {
  const { user } = useAuth();
  const home = useAsync(() => api.studentHome(), []);
  if (home.loading) return <Loading label="Loading your home…" />;
  if (home.error) return <ErrorBox error={home.error} retry={home.reload} />;
  const data = home.data;
  if (!data) return null;
  const first = user?.display_name.split(/\s+/)[0] ?? "";

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Welcome back{first ? `, ${first}` : ""}</h1>
          <p className="lead" style={{ marginBottom: 0 }}>Here is what needs your attention.</p>
        </div>
        <Link className="btn" to="/classes">
          All classes
        </Link>
      </header>

      {data.courses.length === 0 && (
        <Empty title="You are not in a class yet">
          Join one with the code from your teacher on the <Link to="/classes">Classes</Link> page.
        </Empty>
      )}

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="card stack">
          <h2 style={{ fontSize: 16, margin: 0 }}>Due soon</h2>
          {data.due_soon.length === 0 && <span className="small dim">Nothing due. Nice.</span>}
          {data.due_soon.map((item) => (
            <Link key={item.assignment_id} className="home-row" to={`/classes/${item.course_id}/classwork/${item.assignment_id}`}>
              <div>
                <div style={{ fontWeight: 600 }}>{item.title}</div>
                <div className="small dim">{item.course_code}</div>
              </div>
              {item.is_overdue ? (
                <Badge tone="red">overdue</Badge>
              ) : (
                <span className="small">{item.due_at ? formatDateTime(item.due_at) : "no due date"}</span>
              )}
            </Link>
          ))}
        </section>

        <section className="card stack">
          <h2 style={{ fontSize: 16, margin: 0 }}>Recently returned</h2>
          {data.feedback.length === 0 && <span className="small dim">Returned work and feedback will show up here.</span>}
          {data.feedback.map((item) => (
            <Link key={item.submission_id} className="home-row" to={`/classes/${item.course_id}/classwork/${item.assignment_id}`}>
              <div>
                <div style={{ fontWeight: 600 }}>{item.assignment_title}</div>
                <div className="small dim">
                  {relativeTime(item.released_at)}
                  {item.has_comments && " · has comments"}
                </div>
              </div>
              <strong>
                {item.final_score ?? "—"}/{item.max_points}
              </strong>
            </Link>
          ))}
        </section>
      </div>

      <section className="card stack">
        <h2 style={{ fontSize: 16, margin: 0 }}>Latest from your classes</h2>
        {data.posts.length === 0 && <span className="small dim">No announcements yet.</span>}
        {data.posts.map((post) => (
          <Link key={post.id} className="home-row" to={`/classes/${post.course_id}/stream#post-${post.id}`}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>
                {!post.is_read && <span className="unread-dot" aria-label="unread" />}
                {post.title || post.excerpt.split("\n")[0] || "Announcement"}
              </div>
              <div className="small dim">
                {post.course_code} · {post.kind} · {relativeTime(post.published_at)}
              </div>
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
