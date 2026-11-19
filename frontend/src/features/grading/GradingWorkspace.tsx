import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { SubmissionDetailOut, SubmissionOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { formatDateTime, errorMessage } from "../../components/kit";
import { NotebookView } from "../../components/NotebookView";

type Filter = "all" | "submitted" | "draft" | "returned" | "late";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "submitted", label: "To grade" },
  { key: "draft", label: "Drafts" },
  { key: "returned", label: "Returned" },
  { key: "late", label: "Late" },
  { key: "all", label: "All" },
];

function statusBadge(s: SubmissionOut) {
  if (s.status === "returned" && !s.has_draft) return <Badge tone="green">returned</Badge>;
  if (s.status === "graded" || s.has_draft) return <Badge tone="purple">draft</Badge>;
  return <Badge tone="amber">to grade</Badge>;
}

/** Latest attempt per student, newest submissions first. */
function latestPerStudent(rows: SubmissionOut[]): SubmissionOut[] {
  const latest = new Map<string, SubmissionOut>();
  for (const row of rows) {
    const current = latest.get(row.user_id);
    if (!current || row.attempt_number > current.attempt_number) latest.set(row.user_id, row);
  }
  return [...latest.values()].sort((a, b) => b.submitted_at.localeCompare(a.submitted_at));
}

export function GradingWorkspace() {
  const { assignmentId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const selected = params.get("s") ?? "";
  const [filter, setFilter] = useState<Filter>("submitted");

  const assignment = useAsync(() => api.assignment(assignmentId), [assignmentId]);
  const submissions = useAsync(() => api.submissions(assignmentId, { limit: 200 }), [assignmentId]);

  const select = useCallback(
    (id: string) => {
      const next = new URLSearchParams(params);
      if (id) next.set("s", id);
      else next.delete("s");
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const all = useMemo(() => latestPerStudent(submissions.data?.submissions ?? []), [submissions.data]);
  const counts = useMemo(
    () => ({
      submitted: all.filter((s) => s.status === "submitted").length,
      draft: all.filter((s) => s.status === "graded" || s.has_draft).length,
      returned: all.filter((s) => s.status === "returned" && !s.has_draft).length,
      late: all.filter((s) => s.is_late).length,
      all: all.length,
    }),
    [all],
  );
  const shown = useMemo(() => {
    switch (filter) {
      case "submitted":
        return all.filter((s) => s.status === "submitted");
      case "draft":
        return all.filter((s) => s.status === "graded" || s.has_draft);
      case "returned":
        return all.filter((s) => s.status === "returned" && !s.has_draft);
      case "late":
        return all.filter((s) => s.is_late);
      default:
        return all;
    }
  }, [all, filter]);

  // Start on the "All" list when there is nothing left to grade.
  useEffect(() => {
    if (submissions.data && filter === "submitted" && counts.submitted === 0 && counts.all > 0) setFilter("all");
  }, [submissions.data, filter, counts]);

  // j / k move through the visible list (ignored while typing).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key !== "j" && event.key !== "k") return;
      const index = shown.findIndex((s) => s.id === selected);
      const next = event.key === "j" ? Math.min(shown.length - 1, index + 1) : Math.max(0, index - 1);
      if (shown[next]) select(shown[next].id);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, selected, select]);

  const [returning, setReturning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (assignment.loading) return <Loading label="Loading assignment…" />;
  if (assignment.error) return <ErrorBox error={assignment.error} retry={assignment.reload} />;
  const data = assignment.data;
  if (!data) return null;

  return (
    <div className="stack" style={{ gap: 14 }}>
      <header className="spread" style={{ flexWrap: "wrap", gap: 10 }}>
        <div>
          <Link className="small dim" to={`/classes/${data.course_id}/classwork`}>
            ← Classwork
          </Link>
          <h1 style={{ margin: "4px 0 0" }}>{data.title}</h1>
          <div className="row small dim" style={{ gap: 8, marginTop: 4 }}>
            <span>{data.max_points} pts</span>
            <span>· due {formatDateTime(data.due_at)}</span>
            {!data.is_visible && <Badge tone="amber">not visible to students</Badge>}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {notice && <Badge tone="green">{notice}</Badge>}
          <button
            className="btn btn-primary"
            type="button"
            disabled={counts.draft === 0 || returning}
            onClick={async () => {
              setReturning(true);
              try {
                const result = await api.returnAll(assignmentId);
                setNotice(`Returned ${result.returned}`);
                submissions.reload();
              } catch (cause) {
                setNotice(errorMessage(cause));
              } finally {
                setReturning(false);
              }
            }}
          >
            Return all drafts ({counts.draft})
          </button>
        </div>
      </header>

      <div className="grader">
        <aside className="card grader-list">
          <div className="grader-filters">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={`chip${filter === f.key ? " active" : ""}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label} <span className="dim">{counts[f.key]}</span>
              </button>
            ))}
          </div>
          {submissions.loading && <Loading label="Loading…" />}
          {submissions.error && <ErrorBox error={submissions.error} retry={submissions.reload} />}
          <ul className="list-reset grader-rows">
            {shown.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={`grader-row${s.id === selected ? " active" : ""}`}
                  onClick={() => select(s.id)}
                >
                  <span className="grader-name">{s.student?.display_name ?? s.user_id}</span>
                  <span className="row" style={{ gap: 4 }}>
                    {s.is_late && <Badge tone="red">late</Badge>}
                    {statusBadge(s)}
                  </span>
                  <span className="small dim">
                    attempt {s.attempt_number} · {formatDateTime(s.submitted_at)}
                    {s.final_score !== null ? ` · ${s.final_score}/${data.max_points}` : ""}
                  </span>
                </button>
              </li>
            ))}
            {!submissions.loading && shown.length === 0 && (
              <li className="small dim" style={{ padding: 12 }}>
                Nothing here.
              </li>
            )}
          </ul>
          <div className="small dim" style={{ padding: "8px 4px 0" }}>
            Tip: <kbd>j</kbd>/<kbd>k</kbd> move between students.
          </div>
        </aside>

        {selected ? (
          <SubmissionPanes
            key={selected}
            submissionId={selected}
            onSelect={select}
            onChanged={() => submissions.reload()}
          />
        ) : (
          <div className="card grader-empty">
            <Empty title="Select a student">Pick a submission on the left to view the notebook and grade it.</Empty>
          </div>
        )}
      </div>
    </div>
  );
}

function SubmissionPanes({
  submissionId,
  onSelect,
  onChanged,
}: {
  submissionId: string;
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const detail = useAsync(() => api.submission(submissionId), [submissionId]);
  const notebook = useAsync(() => api.submissionNotebook(submissionId), [submissionId]);
  return (
    <>
      <section className="card grader-notebook">
        {detail.data && (
          <div className="spread" style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <div>
              <strong>{detail.data.student?.display_name}</strong>
              <div className="small dim">
                v{detail.data.notebook_version?.version_number} · sha {detail.data.notebook_version?.sha256.slice(0, 10)}
                {detail.data.is_late && " · late"}
              </div>
            </div>
            <div className="row" style={{ gap: 6 }}>
              {detail.data.attempts.length > 1 && (
                <select
                  className="select"
                  value={submissionId}
                  onChange={(e) => onSelect(e.target.value)}
                  aria-label="Attempt"
                >
                  {detail.data.attempts.map((a) => (
                    <option key={a.id} value={a.id}>
                      Attempt {a.attempt_number} · {formatDateTime(a.submitted_at)}
                      {a.is_late ? " (late)" : ""}
                    </option>
                  ))}
                </select>
              )}
              <a className="btn btn-ghost btn-sm" href={api.submissionDownloadUrl(submissionId)}>
                Download .ipynb
              </a>
            </div>
          </div>
        )}
        {notebook.loading && <Loading label="Loading notebook…" />}
        {notebook.error && <ErrorBox error={notebook.error} retry={notebook.reload} />}
        {notebook.data && <NotebookView document={notebook.data} />}
      </section>
      <section className="card grader-rubric">
        {detail.loading && <Loading label="Loading rubric…" />}
        {detail.error && <ErrorBox error={detail.error} retry={detail.reload} />}
        {detail.data && (
          <GradeForm
            detail={detail.data}
            onSaved={() => {
              detail.reload();
              onChanged();
            }}
          />
        )}
      </section>
    </>
  );
}

interface ScoreDraft {
  points: string;
  comment: string;
}

export function GradeForm({ detail, onSaved }: { detail: SubmissionDetailOut; onSaved: () => void }) {
  const rubric = detail.rubric;
  const latest = detail.latest_grade;
  const [scores, setScores] = useState<Record<string, ScoreDraft>>({});
  const [feedback, setFeedback] = useState("");
  const [override, setOverride] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!rubric) return;
    const draft: Record<string, ScoreDraft> = {};
    for (const criterion of rubric.criteria) {
      const previous = latest?.criteria.find((c) => c.criterion_id === criterion.id);
      draft[criterion.id] = { points: previous ? String(previous.points) : "", comment: previous?.comment ?? "" };
    }
    setScores(draft);
    setFeedback(latest?.feedback ?? "");
    const overridden = latest && latest.final_score !== null && latest.final_score !== latest.total_points;
    setOverride(overridden ? String(latest!.final_score) : "");
    setReason(latest?.override_reason ?? "");
  }, [rubric, latest]);

  if (!rubric) {
    return (
      <Empty title="No rubric">
        This assignment has no rubric yet. Add one from the assignment&apos;s edit page in Classwork.
      </Empty>
    );
  }

  const total = rubric.criteria.reduce((sum, c) => sum + (Number(scores[c.id]?.points) || 0), 0);
  const complete = rubric.criteria.every((c) => scores[c.id]?.points !== "" && scores[c.id]?.points !== undefined);
  const outOfRange = rubric.criteria.some((c) => {
    const value = Number(scores[c.id]?.points);
    return Number.isNaN(value) || value < 0 || value > c.max_points;
  });
  const overriding = override !== "" && Number(override) !== Math.round(total * 100) / 100;

  async function save(release: boolean) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const grade = await api.gradeSubmission(detail.id, {
        criteria: rubric!.criteria.map((c) => ({
          criterion_id: c.id,
          points: Number(scores[c.id]?.points ?? 0),
          comment: scores[c.id]?.comment ?? "",
        })),
        feedback,
        final_score: override === "" ? null : Number(override),
        override_reason: overriding ? reason : null,
        release,
      });
      setMessage(release ? `Returned (revision ${grade.revision})` : `Draft saved (revision ${grade.revision})`);
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function returnDraft() {
    setBusy(true);
    setError(null);
    try {
      await api.returnSubmission(detail.id);
      setMessage("Returned to the student");
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="spread">
        <h2 style={{ fontSize: 16, margin: 0 }}>{rubric.title}</h2>
        {latest ? (
          <Badge tone={latest.state === "draft" ? "purple" : "green"}>
            rev {latest.revision} · {latest.state === "draft" ? "draft" : "returned"}
          </Badge>
        ) : (
          <Badge tone="amber">not graded</Badge>
        )}
      </div>
      {rubric.criteria.map((c) => (
        <div key={c.id} className="stack-sm">
          <div className="spread">
            <label className="small" style={{ fontWeight: 600 }} htmlFor={`pts-${c.id}`}>
              {c.label}
            </label>
            <span className="small dim">/ {c.max_points}</span>
          </div>
          {c.description && <span className="small dim">{c.description}</span>}
          <div className="row" style={{ gap: 6 }}>
            <input
              id={`pts-${c.id}`}
              className="input"
              type="number"
              min={0}
              max={c.max_points}
              step="0.5"
              style={{ width: 90 }}
              value={scores[c.id]?.points ?? ""}
              onChange={(e) =>
                setScores((cur) => ({ ...cur, [c.id]: { points: e.target.value, comment: cur[c.id]?.comment ?? "" } }))
              }
            />
            <input
              className="input"
              placeholder="Comment for the student"
              value={scores[c.id]?.comment ?? ""}
              onChange={(e) =>
                setScores((cur) => ({ ...cur, [c.id]: { points: cur[c.id]?.points ?? "", comment: e.target.value } }))
              }
            />
          </div>
        </div>
      ))}
      <div className="spread">
        <span className="small">Rubric total</span>
        <strong>
          {Math.round(total * 100) / 100} / {rubric.total_points}
        </strong>
      </div>
      <label className="field">
        <span className="label">Overall feedback</span>
        <textarea className="textarea" rows={4} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
      </label>
      <details>
        <summary className="small dim">Override final score</summary>
        <div className="stack-sm" style={{ marginTop: 8 }}>
          <input
            className="input"
            type="number"
            min={0}
            step="0.5"
            placeholder={`Leave blank to use ${Math.round(total * 100) / 100}`}
            value={override}
            onChange={(e) => setOverride(e.target.value)}
          />
          {overriding && (
            <input
              className="input"
              placeholder="Reason (required, kept in the grade history)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </div>
      </details>
      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice notice-success">{message}</div>}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn" type="button" disabled={busy || !complete || outOfRange || (overriding && !reason.trim())} onClick={() => save(false)}>
          Save draft
        </button>
        <button className="btn btn-primary" type="button" disabled={busy || !complete || outOfRange || (overriding && !reason.trim())} onClick={() => save(true)}>
          Save &amp; return
        </button>
        {latest?.state === "draft" && (
          <button className="btn btn-ghost" type="button" disabled={busy} onClick={returnDraft}>
            Return saved draft
          </button>
        )}
      </div>
      <span className="small dim">Drafts are visible only to course staff until returned.</span>
    </div>
  );
}
