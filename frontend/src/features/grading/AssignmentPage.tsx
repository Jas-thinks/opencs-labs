import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { GradeOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading, formatDate } from "../../components/ui";

interface ScoreDraft {
  points: string;
  comment: string;
}

export function AssignmentPage() {
  const { assignmentId = "" } = useParams();
  const assignment = useAsync(() => api.assignment(assignmentId), [assignmentId]);
  const rubric = useAsync(() => api.rubric(assignmentId), [assignmentId]);
  const submissions = useAsync(
    () => api.submissions(assignmentId, { limit: 100 }),
    [assignmentId],
  );
  const [selected, setSelected] = useState("");
  const grades = useAsync(
    () =>
      selected
        ? api.submissionGrades(selected)
        : Promise.resolve(null),
    [selected],
  );

  const [scores, setScores] = useState<Record<string, ScoreDraft>>({});
  const [feedback, setFeedback] = useState("");
  const [finalScore, setFinalScore] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const latestGrade: GradeOut | null = grades.data?.grades?.[0] ?? null;

  useEffect(() => {
    if (!rubric.data) return;
    const draft: Record<string, ScoreDraft> = {};
    for (const criterion of rubric.data.criteria) {
      const previous = latestGrade?.criteria.find(
        (item) => item.criterion_id === criterion.id,
      );
      draft[criterion.id] = {
        points: String(previous?.points ?? 0),
        comment: previous?.comment ?? "",
      };
    }
    setScores(draft);
    setFeedback(latestGrade?.feedback ?? "");
    setFinalScore(latestGrade?.final_score !== null && latestGrade ? String(latestGrade.final_score) : "");
    setMessage(null);
    setError(null);
  }, [rubric.data, latestGrade, selected]);

  async function submitGrade() {
    if (!rubric.data || !selected) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const grade = await api.gradeSubmission(selected, {
        criteria: rubric.data.criteria.map((criterion) => ({
          criterion_id: criterion.id,
          points: Number(scores[criterion.id]?.points ?? 0),
          comment: scores[criterion.id]?.comment ?? "",
        })),
        feedback,
        final_score: finalScore === "" ? null : Number(finalScore),
      });
      setMessage(`Published revision ${grade.revision} (${grade.final_score ?? grade.total_points} points).`);
      grades.reload();
      submissions.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (assignment.loading) return <Loading label="Loading assignment…" />;
  if (assignment.error) return <ErrorBox error={assignment.error} retry={assignment.reload} />;
  const data = assignment.data;
  if (!data) return null;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>{data.title}</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            {data.description || "No description."}
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Badge tone={data.is_published ? "green" : "amber"}>
            {data.is_published ? "published" : "draft"}
          </Badge>
          <Badge tone="neutral">{data.kind}</Badge>
          <Badge tone="neutral">{data.max_points} pts</Badge>
        </div>
      </header>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="card stack">
          <div className="spread">
            <h2 style={{ fontSize: 16 }}>Submissions</h2>
            {submissions.data && (
              <span className="small dim">{submissions.data.submissions.length} shown</span>
            )}
          </div>
          {submissions.loading && <Loading label="Loading submissions…" />}
          {submissions.error && (
            <ErrorBox error={submissions.error} retry={submissions.reload} />
          )}
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Attempt</th>
                  <th>Status</th>
                  <th>Score</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {(submissions.data?.submissions ?? []).map((submission) => (
                  <tr
                    key={submission.id}
                    onClick={() => setSelected(submission.id)}
                    style={{
                      cursor: "pointer",
                      background: selected === submission.id ? "var(--bg-raised)" : undefined,
                    }}
                  >
                    <td>{submission.student?.display_name ?? submission.user_id}</td>
                    <td>{submission.attempt_number}</td>
                    <td>
                      <Badge tone={submission.status === "graded" ? "green" : "amber"}>
                        {submission.status}
                      </Badge>
                      {submission.is_late && <Badge tone="red">late</Badge>}
                    </td>
                    <td>{submission.final_score ?? "—"}</td>
                    <td>{formatDate(submission.submitted_at)}</td>
                  </tr>
                ))}
                {(submissions.data?.submissions ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5}>No submissions yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card stack">
          <h2 style={{ fontSize: 16 }}>Grade</h2>
          {!selected && <Empty title="Select a submission">Pick a row on the left to grade it.</Empty>}
          {selected && rubric.error && (
            <ErrorBox error={rubric.error} retry={rubric.reload} />
          )}
          {selected && rubric.loading && <Loading label="Loading rubric…" />}
          {selected && rubric.data && (
            <>
              <div className="spread">
                <span className="small dim">
                  Latest revision: {latestGrade ? latestGrade.revision : "none"}
                </span>
                <span className="small dim">Rubric total {rubric.data.total_points}</span>
              </div>
              {rubric.data.criteria.map((criterion) => (
                <div key={criterion.id} className="stack-sm">
                  <div className="spread">
                    <span className="small" style={{ fontWeight: 600 }}>
                      {criterion.label}
                    </span>
                    <span className="small dim">max {criterion.max_points}</span>
                  </div>
                  {criterion.description && (
                    <span className="small dim">{criterion.description}</span>
                  )}
                  <div className="row" style={{ gap: 8 }}>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      max={criterion.max_points}
                      step="0.5"
                      style={{ maxWidth: 110 }}
                      value={scores[criterion.id]?.points ?? "0"}
                      onChange={(event) =>
                        setScores((current) => ({
                          ...current,
                          [criterion.id]: {
                            points: event.target.value,
                            comment: current[criterion.id]?.comment ?? "",
                          },
                        }))
                      }
                    />
                    <input
                      className="input"
                      placeholder="Comment (optional)"
                      value={scores[criterion.id]?.comment ?? ""}
                      onChange={(event) =>
                        setScores((current) => ({
                          ...current,
                          [criterion.id]: {
                            points: current[criterion.id]?.points ?? "0",
                            comment: event.target.value,
                          },
                        }))
                      }
                    />
                  </div>
                </div>
              ))}
              <label className="field">
                <span className="label">Overall feedback</span>
                <textarea
                  className="textarea"
                  rows={3}
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                />
              </label>
              <label className="field">
                <span className="label">Final score override (optional)</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step="0.5"
                  placeholder="Leave blank to use the rubric total"
                  value={finalScore}
                  onChange={(event) => setFinalScore(event.target.value)}
                />
              </label>
              <div className="row">
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={submitGrade}
                  disabled={busy}
                >
                  {busy ? "Publishing…" : "Publish grade"}
                </button>
                {message && <Badge tone="green">{message}</Badge>}
              </div>
              {error && <ErrorBox error={error} />}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
