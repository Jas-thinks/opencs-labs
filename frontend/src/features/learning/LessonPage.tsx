import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { StageView } from "../../components/Blocks";
import { Badge, ErrorBox, Loading, Progress, difficultyTone } from "../../components/ui";

export function LessonPage() {
  const { lessonSlug = "" } = useParams();
  const navigate = useNavigate();
  const { data, loading, error, reload } = useAsync(() => api.lesson(lessonSlug), [lessonSlug]);

  const [stageIndex, setStageIndex] = useState(0);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("not_started");

  const stages = useMemo(() => data?.content.stages ?? [], [data]);

  useEffect(() => {
    setStageIndex(0);
    setLaunchError(null);
    if (data) {
      setStatus(data.progress.status);
      // Mark as in-progress on first view, without clobbering "completed".
      if (data.progress.status === "not_started") {
        void api.updateProgress(lessonSlug, "in_progress").catch(() => undefined);
      }
    }
  }, [data, lessonSlug]);

  async function handleLaunch() {
    setLaunching(true);
    setLaunchError(null);
    try {
      const result = await api.launchLesson(lessonSlug);
      window.open(result.url, "_blank", "noopener,noreferrer");
      setStatus((current) => (current === "completed" ? current : "in_progress"));
    } catch (cause) {
      if (cause instanceof ApiError) {
        setLaunchError(
          cause.code === "UPSTREAM_UNAVAILABLE"
            ? "The notebook service is not reachable right now. Your lesson progress is safe — try again once JupyterHub is available."
            : cause.message,
        );
      } else {
        setLaunchError("Could not open the lesson notebook.");
      }
    } finally {
      setLaunching(false);
    }
  }

  async function handleComplete() {
    const result = await api.updateProgress(lessonSlug, "completed", stages[stageIndex]?.key);
    setStatus(result.status);
    if (data?.navigation.next) {
      navigate(`/learn/${data.navigation.next}`);
    }
  }

  if (loading) return <Loading label="Loading lesson…" />;
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return null;

  const current = stages[stageIndex];
  const progressPercent = stages.length ? Math.round(((stageIndex + 1) / stages.length) * 100) : 0;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <nav className="small dim row" style={{ gap: 6 }}>
        <Link to="/learn">Learn</Link>
        <span>/</span>
        <span>{data.module.title}</span>
        <span>/</span>
        <span style={{ color: "var(--text)" }}>{data.title}</span>
      </nav>

      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 700 }}>
          <div className="row" style={{ gap: 8, marginBottom: 8 }}>
            <Badge tone="accent">{data.module.title}</Badge>
            <Badge tone="neutral">{data.estimated_minutes} min</Badge>
            {status === "completed" && <Badge tone="green">Completed</Badge>}
            {status === "in_progress" && <Badge tone="amber">In progress</Badge>}
          </div>
          <h1>{data.title}</h1>
          <p className="lead">{data.objective}</p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {data.has_notebook_activity && (
            <button className="btn btn-primary" type="button" onClick={handleLaunch} disabled={launching}>
              {launching ? <span className="spinner" /> : null}
              {launching ? "Opening…" : "Open in Notebook"}
            </button>
          )}
        </div>
      </header>

      {launchError && <div className="notice notice-warn">{launchError}</div>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="tabs" style={{ padding: "0 12px", marginBottom: 0 }}>
          {stages.map((stage, index) => (
            <button
              key={stage.key}
              type="button"
              className={`tab${index === stageIndex ? " active" : ""}`}
              onClick={() => setStageIndex(index)}
            >
              {index + 1}. {stage.label}
            </button>
          ))}
        </div>
        <div style={{ padding: 22 }}>
          {current ? <StageView stage={current} /> : <div className="dim">No content yet.</div>}
        </div>
        <div style={{ padding: "14px 22px", borderTop: "1px solid var(--border)" }}>
          <div className="spread">
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => setStageIndex((index) => Math.max(0, index - 1))}
              disabled={stageIndex === 0}
            >
              ← Back
            </button>
            <div className="row" style={{ gap: 8 }}>
              <span className="small dim">
                Stage {stageIndex + 1} of {stages.length}
              </span>
              {stageIndex < stages.length - 1 ? (
                <button
                  className="btn btn-primary btn-sm"
                  type="button"
                  onClick={() => setStageIndex((index) => Math.min(stages.length - 1, index + 1))}
                >
                  Next →
                </button>
              ) : (
                <button className="btn btn-primary btn-sm" type="button" onClick={handleComplete}>
                  Mark complete
                </button>
              )}
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <Progress percent={progressPercent} />
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <section className="card stack-sm">
          <h2 style={{ marginBottom: 6 }}>Takeaways</h2>
          <ul className="list-reset stack-sm">
            {(data.content.takeaways ?? []).map((item, index) => (
              <li key={index} className="row" style={{ gap: 9, alignItems: "flex-start" }}>
                <span style={{ color: "var(--accent-strong)" }}>•</span>
                <span className="small">{item}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card stack-sm">
          <h2 style={{ marginBottom: 6 }}>Continue with</h2>
          {data.datasets.length > 0 && (
            <div className="stack-sm">
              <span className="small dim">Datasets in this lesson</span>
              {data.datasets.map((dataset) => (
                <Link key={dataset.slug} to={`/datasets/${dataset.slug}`} className="row" style={{ gap: 8 }}>
                  <Badge tone="accent">{dataset.format ?? "data"}</Badge>
                  <span className="small">{dataset.title}</span>
                </Link>
              ))}
            </div>
          )}
          {data.exercises.length > 0 && (
            <div className="stack-sm" style={{ marginTop: 8 }}>
              <span className="small dim">Practise this</span>
              {data.exercises.map((exercise) => (
                <Link key={exercise.slug} to={`/practice/${exercise.slug}`} className="row" style={{ gap: 8 }}>
                  <Badge tone={difficultyTone(exercise.difficulty)}>{exercise.difficulty}</Badge>
                  <span className="small">{exercise.title}</span>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="spread">
        {data.navigation.previous ? (
          <Link to={`/learn/${data.navigation.previous}`} className="btn btn-ghost">
            ← Previous lesson
          </Link>
        ) : (
          <span />
        )}
        {data.navigation.next && (
          <Link to={`/learn/${data.navigation.next}`} className="btn">
            Next lesson →
          </Link>
        )}
      </div>
    </div>
  );
}
