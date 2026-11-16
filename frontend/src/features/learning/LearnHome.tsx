import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading, Progress } from "../../components/ui";
import type { LessonSummary, ModuleSummary } from "../../api/types";

function LessonRow({ lesson }: { lesson: LessonSummary }) {
  const done = lesson.status === "completed";
  const started = lesson.status === "in_progress";
  return (
    <Link to={`/learn/${lesson.slug}`} className="card card-link" style={{ padding: 14 }}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 8, marginBottom: 4 }}>
            <span style={{ fontWeight: 650, fontSize: 14.5 }}>{lesson.title}</span>
            {done && <Badge tone="green">Completed</Badge>}
            {started && <Badge tone="amber">In progress</Badge>}
            {lesson.has_notebook_activity && <Badge tone="accent">Notebook</Badge>}
          </div>
          <p className="small muted" style={{ marginBottom: 0, maxWidth: 620 }}>
            {lesson.summary}
          </p>
        </div>
        <span className="small dim" style={{ whiteSpace: "nowrap" }}>
          {lesson.estimated_minutes} min
        </span>
      </div>
    </Link>
  );
}

function ModuleCard({ module }: { module: ModuleSummary }) {
  const percent = module.total_lessons
    ? Math.round((module.completed_lessons / module.total_lessons) * 100)
    : 0;
  return (
    <section className="stack-sm">
      <div className="spread">
        <div>
          <h2 style={{ marginBottom: 2 }}>{module.title}</h2>
          <p className="small muted" style={{ marginBottom: 6 }}>
            {module.description}
          </p>
        </div>
        <div className="small dim" style={{ whiteSpace: "nowrap" }}>
          {module.completed_lessons}/{module.total_lessons} lessons
        </div>
      </div>
      <Progress percent={percent} />
      <div className="stack-sm" style={{ marginTop: 6 }}>
        {module.lessons.map((lesson) => (
          <LessonRow key={lesson.slug} lesson={lesson} />
        ))}
      </div>
    </section>
  );
}

export function LearnHome() {
  const { data, loading, error, reload } = useAsync(() => api.paths(), []);

  if (loading) return <Loading label="Loading curriculum…" />;
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return null;

  const path = data.paths[0];
  const percent = path && path.total_lessons
    ? Math.round((path.completed_lessons / path.total_lessons) * 100)
    : 0;

  return (
    <div className="stack" style={{ gap: 28 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 680 }}>
          <h1>{path?.title ?? "Learning paths"}</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            {path?.description ?? "Structured lessons from your first table to a boosted model."}
          </p>
        </div>
        <div className="card" style={{ minWidth: 220 }}>
          <div className="kpi">
            <span className="kpi-label">Your progress</span>
            <span className="kpi-value">
              {percent}% <span className="small dim" style={{ fontWeight: 500 }}>complete</span>
            </span>
          </div>
          <div style={{ margin: "10px 0 6px" }}>
            <Progress percent={percent} />
          </div>
          <span className="small dim">
            {data.completed_lessons} of {data.total_lessons} lessons completed
          </span>
        </div>
      </header>

      <div className="grid" style={{ gap: 34 }}>
        {data.paths.map((item) =>
          item.modules.map((module) => <ModuleCard key={module.slug} module={module} />),
        )}
      </div>
    </div>
  );
}
