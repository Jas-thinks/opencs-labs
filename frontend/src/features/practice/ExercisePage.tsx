import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Prose } from "../../components/Blocks";
import { Badge, ErrorBox, Loading, difficultyTone } from "../../components/ui";
import type { AttemptOut, FeedbackResponse } from "../../api/types";

export function ExercisePage() {
  const { exerciseSlug = "" } = useParams();
  const { data, loading, error, reload } = useAsync(() => api.exercise(exerciseSlug), [exerciseSlug]);

  const [attempt, setAttempt] = useState<AttemptOut | null>(null);
  const [notebookUrl, setNotebookUrl] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(0);
  const [feedback, setFeedback] = useState<FeedbackResponse | null>(null);
  const [busy, setBusy] = useState<"start" | "evaluate" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  function explain(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError) {
      if (cause.code === "UPSTREAM_UNAVAILABLE") {
        return "The notebook or grading service is unavailable right now. Nothing was lost — retry when the service is back.";
      }
      return cause.message;
    }
    return fallback;
  }

  async function handleStart() {
    setBusy("start");
    setActionError(null);
    setFeedback(null);
    try {
      const result = await api.createAttempt(exerciseSlug);
      setAttempt(result.attempt);
      setNotebookUrl(result.url);
      setRevealed(0);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setActionError(explain(cause, "Could not start an attempt."));
    } finally {
      setBusy(null);
    }
  }

  async function handleEvaluate() {
    if (!attempt) return;
    setBusy("evaluate");
    setActionError(null);
    try {
      const result = await api.evaluateAttempt(attempt.id);
      setFeedback(result);
      if (notebookUrl) {
        window.open(notebookUrl, "_blank", "noopener,noreferrer");
      }
    } catch (cause) {
      setActionError(explain(cause, "Could not evaluate this attempt."));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loading label="Loading exercise…" />;
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return null;

  const instructionText = data.instructions.markdown ?? "";

  return (
    <div className="stack" style={{ gap: 20 }}>
      <nav className="small dim row" style={{ gap: 6 }}>
        <Link to="/practice">Practice</Link>
        <span>/</span>
        <span style={{ color: "var(--text)" }}>{data.title}</span>
      </nav>

      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 720 }}>
          <div className="row" style={{ gap: 6, marginBottom: 8 }}>
            <Badge tone={difficultyTone(data.difficulty)}>{data.difficulty}</Badge>
            <Badge tone="neutral">{data.topic}</Badge>
            <Badge tone="neutral">{data.estimated_minutes} min</Badge>
            {data.completed && <Badge tone="green">Completed</Badge>}
            {data.has_automated_checks ? (
              <Badge tone="accent">Automated checks</Badge>
            ) : (
              <Badge tone="amber">Instructor assessed</Badge>
            )}
          </div>
          <h1>{data.title}</h1>
          <p className="lead">{data.objective}</p>
        </div>
      </header>

      {actionError && <div className="notice notice-error">{actionError}</div>}

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 320px", alignItems: "start" }}>
        <div className="stack">
          <section className="card">
            <h2 style={{ marginBottom: 10 }}>Task</h2>
            <Prose text={instructionText} />
          </section>

          {feedback && (
            <section className={`card stack-sm`}>
              <div className="spread">
                <h2 style={{ marginBottom: 0 }}>Feedback</h2>
                {feedback.passed ? (
                  <Badge tone="green">Passed · {Math.round((feedback.score ?? 0) * 100)}%</Badge>
                ) : (
                  <Badge tone="red">Not yet · {Math.round((feedback.score ?? 0) * 100)}%</Badge>
                )}
              </div>
              {feedback.message && <div className="notice notice-warn">{feedback.message}</div>}
              <div className="stack-sm" style={{ marginTop: 6 }}>
                {feedback.tests.map((test) => (
                  <div key={test.id} className="row" style={{ gap: 9, alignItems: "flex-start" }}>
                    <span style={{ color: test.passed ? "var(--green)" : "var(--red)", flex: "0 0 auto" }}>
                      {test.passed ? "✓" : "✕"}
                    </span>
                    <div>
                      <div className="small" style={{ fontWeight: 600 }}>
                        {test.description || test.id}
                      </div>
                      {!test.passed && test.message && (
                        <div className="small dim mono" style={{ whiteSpace: "pre-wrap" }}>
                          {test.message}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {data.related_lesson_slug && (
            <Link to={`/learn/${data.related_lesson_slug}`} className="card card-link">
              <span className="small dim">Related lesson</span>
              <div style={{ fontWeight: 600 }}>Review the concept before you continue →</div>
            </Link>
          )}
        </div>

        <aside className="stack">
          <section className="card stack-sm">
            <h2 style={{ marginBottom: 4 }}>Notebook</h2>
            <p className="small muted">
              Opens your own isolated Jupyter notebook with the starter cells. Nothing is shared with
              other students.
            </p>
            {notebookUrl && (
              <a className="btn btn-ghost btn-sm btn-block" href={notebookUrl} target="_blank" rel="noreferrer">
                Reopen notebook ↗
              </a>
            )}
            <button
              className="btn btn-primary btn-block"
              type="button"
              onClick={handleStart}
              disabled={busy !== null}
            >
              {busy === "start" ? <span className="spinner" /> : null}
              {busy === "start" ? "Starting…" : attempt ? "Start another attempt" : "Open practice notebook"}
            </button>
            {attempt && (
              <>
                <div className="small dim">
                  Attempt #{attempt.attempt_number} · {attempt.status.replace("_", " ")}
                </div>
                {data.has_automated_checks && (
                  <button
                    className="btn btn-block"
                    type="button"
                    onClick={handleEvaluate}
                    disabled={busy !== null}
                  >
                    {busy === "evaluate" ? <span className="spinner" /> : null}
                    {busy === "evaluate" ? "Evaluating…" : "Run checks"}
                  </button>
                )}
              </>
            )}
          </section>

          <section className="card stack-sm">
            <h2 style={{ marginBottom: 4 }}>Hints</h2>
            {data.hints.length === 0 && <span className="small dim">No hints for this exercise.</span>}
            <div className="stack-sm">
              {data.hints.slice(0, revealed).map((hint) => (
                <div key={hint.index} className="callout callout-tip">
                  <Prose text={hint.text} />
                </div>
              ))}
            </div>
            {revealed < data.hints.length && (
              <button
                className="btn btn-ghost btn-sm btn-block"
                type="button"
                onClick={() => setRevealed((count) => count + 1)}
              >
                Reveal hint {revealed + 1} of {data.hints.length}
              </button>
            )}
          </section>

          {data.datasets.length > 0 && (
            <section className="card stack-sm">
              <h2 style={{ marginBottom: 4 }}>Datasets</h2>
              {data.datasets.map((dataset) => (
                <Link key={dataset.slug} to={`/datasets/${dataset.slug}`} className="row" style={{ gap: 8 }}>
                  <Badge tone="accent">{dataset.format ?? "data"}</Badge>
                  <span className="small">{dataset.title}</span>
                </Link>
              ))}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
