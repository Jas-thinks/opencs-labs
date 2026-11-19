import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { AssignmentInput, AssignmentOut, RubricOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { ConfirmButton, MarkdownField, errorMessage, fromLocalInput, toLocalInput } from "../../components/kit";
import { useCourse } from "./CourseShell";
import { visibilityBadge } from "./ClassworkTab";

type PublishMode = "draft" | "now" | "schedule";

/** Create or edit an assignment (instructors). The rubric is edited below once saved. */
export function AssignmentEditor() {
  const { assignmentId } = useParams();
  const { course, isInstructor } = useCourse();
  const existing = useAsync(
    () => (assignmentId ? api.assignment(assignmentId) : Promise.resolve(null)),
    [assignmentId],
  );
  if (!isInstructor) {
    return <ErrorBox error={new Error("Only the class instructor can edit assignments.")} />;
  }
  if (existing.loading) return <Loading label="Loading assignment…" />;
  if (existing.error) return <ErrorBox error={existing.error} retry={existing.reload} />;
  return (
    <div className="stack" style={{ gap: 20, maxWidth: 900 }}>
      <Link className="small dim" to={`/classes/${course.id}/classwork`}>
        ← Classwork
      </Link>
      <AssignmentForm key={existing.data?.id ?? "new"} existing={existing.data} onSaved={existing.reload} />
      {existing.data && <RubricEditor assignment={existing.data} />}
    </div>
  );
}

function AssignmentForm({ existing, onSaved }: { existing: AssignmentOut | null; onSaved: () => void }) {
  const { course } = useCourse();
  const navigate = useNavigate();
  const notebooks = useAsync(() => api.notebooks(), []);
  const initialMode: PublishMode = !existing
    ? "draft"
    : !existing.is_published
      ? "draft"
      : existing.publish_at && !existing.is_visible
        ? "schedule"
        : "now";
  const [title, setTitle] = useState(existing?.title ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [kind, setKind] = useState<AssignmentInput["kind"]>((existing?.kind as AssignmentInput["kind"]) ?? "project");
  const [topic, setTopic] = useState(existing?.topic ?? "");
  const [dueAt, setDueAt] = useState(toLocalInput(existing?.due_at));
  const [mode, setMode] = useState<PublishMode>(initialMode);
  const [publishAt, setPublishAt] = useState(toLocalInput(existing?.publish_at));
  const [maxPoints, setMaxPoints] = useState(String(existing?.max_points ?? 100));
  const [weight, setWeight] = useState(String(existing?.weight ?? 1));
  const [allowLate, setAllowLate] = useState(existing?.allow_late ?? true);
  const [penalty, setPenalty] = useState(String(existing?.late_penalty_pct ?? 0));
  const [exercise, setExercise] = useState(existing?.exercise_slug ?? "");
  const [starter, setStarter] = useState("");
  const [clearStarter, setClearStarter] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const locked = Boolean(existing?.submission_count);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(null);
    const payload: AssignmentInput = {
      title,
      description,
      kind,
      topic: topic.trim() || null,
      due_at: fromLocalInput(dueAt),
      is_published: mode !== "draft",
      publish_at: mode === "schedule" ? fromLocalInput(publishAt) : null,
      max_points: Number(maxPoints),
      weight: Number(weight),
      allow_late: allowLate,
      late_penalty_pct: Number(penalty),
      exercise_slug: exercise.trim() || null,
    };
    if (starter) payload.starter_notebook_id = starter;
    if (clearStarter) payload.clear_starter = true;
    try {
      if (existing) {
        await api.updateAssignment(existing.id, payload);
        setSaved("Saved");
        setStarter("");
        setClearStarter(false);
        onSaved();
      } else {
        const created = await api.createAssignment(course.id, payload);
        navigate(`/classes/${course.id}/classwork/${created.id}/edit`, { replace: true });
      }
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack">
      <div className="spread">
        <h1 style={{ fontSize: 20, margin: 0 }}>{existing ? "Edit assignment" : "New assignment"}</h1>
        {existing && visibilityBadge(existing)}
      </div>
      <label className="field">
        <span className="label">Title</span>
        <input className="input" value={title} maxLength={240} onChange={(e) => setTitle(e.target.value)} required />
      </label>
      <MarkdownField label="Instructions" value={description} onChange={setDescription} rows={8} placeholder="What students need to do, how it is graded…" />
      <div className="grid grid-3">
        <label className="field">
          <span className="label">Type</span>
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value as AssignmentInput["kind"])}>
            <option value="practice">Practice</option>
            <option value="project">Project</option>
            <option value="exam">Exam</option>
          </select>
        </label>
        <label className="field">
          <span className="label">Topic</span>
          <input className="input" value={topic} maxLength={120} onChange={(e) => setTopic(e.target.value)} placeholder="Week 3" />
        </label>
        <label className="field">
          <span className="label">Due</span>
          <input className="input" type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
        </label>
        <label className="field">
          <span className="label">Points</span>
          <input className="input" type="number" min={1} step="1" value={maxPoints} onChange={(e) => setMaxPoints(e.target.value)} />
        </label>
        <label className="field">
          <span className="label">Weight in gradebook</span>
          <input className="input" type="number" min={0} step="0.5" value={weight} onChange={(e) => setWeight(e.target.value)} />
        </label>
        <label className="field">
          <span className="label">Late penalty %</span>
          <input className="input" type="number" min={0} max={100} value={penalty} disabled={!allowLate} onChange={(e) => setPenalty(e.target.value)} />
        </label>
      </div>
      <label className="row small" style={{ gap: 6 }}>
        <input type="checkbox" checked={allowLate} onChange={(e) => setAllowLate(e.target.checked)} />
        Accept late submissions (flagged as late)
      </label>

      <fieldset className="fieldset">
        <legend className="label">Starter notebook</legend>
        {existing?.has_starter && !clearStarter && (
          <div className="row small" style={{ gap: 8 }}>
            <Badge tone="green">starter attached</Badge>
            <label className="row" style={{ gap: 6 }}>
              <input type="checkbox" checked={clearStarter} onChange={(e) => setClearStarter(e.target.checked)} /> Remove
            </label>
          </div>
        )}
        <select className="select" value={starter} onChange={(e) => setStarter(e.target.value)} disabled={clearStarter}>
          <option value="">{existing?.has_starter ? "Keep current starter" : "No starter (students start blank)"}</option>
          {(notebooks.data?.notebooks ?? []).map((n) => (
            <option key={n.id} value={n.id}>
              {existing?.has_starter ? "Replace with: " : ""}
              {n.title}
            </option>
          ))}
        </select>
        <span className="small dim">
          A snapshot of your notebook is taken when you save; each student gets their own copy with outputs cleared.
        </span>
      </fieldset>

      <label className="field">
        <span className="label">Linked practice exercise (optional slug)</span>
        <input className="input mono" value={exercise} onChange={(e) => setExercise(e.target.value)} placeholder="pandas-select-iris" />
      </label>

      <fieldset className="fieldset">
        <legend className="label">Visibility</legend>
        <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
          {(["draft", "now", "schedule"] as const).map((m) => (
            <label key={m} className="row small" style={{ gap: 6 }}>
              <input
                type="radio"
                name="publish"
                checked={mode === m}
                disabled={locked && m === "draft"}
                onChange={() => setMode(m)}
              />
              {m === "draft" ? "Draft (hidden)" : m === "now" ? "Publish now" : "Schedule"}
            </label>
          ))}
          {mode === "schedule" && (
            <input className="input" type="datetime-local" value={publishAt} onChange={(e) => setPublishAt(e.target.value)} />
          )}
        </div>
        {locked && <span className="small dim">Students have turned in work, so this cannot go back to draft. Archive it instead.</span>}
      </fieldset>

      {error && <div className="notice notice-error">{error}</div>}
      <div className="spread">
        <span>{saved && <Badge tone="green">{saved}</Badge>}</span>
        <div className="row" style={{ gap: 8 }}>
          {existing && <DangerZone assignment={existing} />}
          <button className="btn btn-primary" type="button" onClick={save} disabled={busy || !title.trim()}>
            {busy ? "Saving…" : existing ? "Save changes" : "Create assignment"}
          </button>
        </div>
      </div>
      {!existing && (
        <span className="small dim">A one-criterion &ldquo;Overall&rdquo; rubric is created automatically; refine it after saving.</span>
      )}
    </section>
  );
}

function DangerZone({ assignment }: { assignment: AssignmentOut }) {
  const { course } = useCourse();
  const navigate = useNavigate();
  const back = () => navigate(`/classes/${course.id}/classwork`);
  if (assignment.submission_count) {
    return assignment.archived_at ? (
      <button className="btn" type="button" onClick={async () => { await api.archiveAssignment(assignment.id, false); back(); }}>
        Restore
      </button>
    ) : (
      <ConfirmButton label="Archive" confirmLabel="Archive assignment" onConfirm={async () => { await api.archiveAssignment(assignment.id, true); back(); }} />
    );
  }
  return (
    <ConfirmButton label="Delete" confirmLabel="Delete assignment" danger onConfirm={async () => { await api.deleteAssignment(assignment.id); back(); }} />
  );
}

interface CriterionDraft {
  id?: string;
  key: string;
  label: string;
  description: string;
  max_points: string;
}

function slugKey(label: string, taken: Set<string>): string {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50) || "criterion";
  let key = base;
  let n = 2;
  while (taken.has(key)) key = `${base}-${n++}`;
  return key;
}

function RubricEditor({ assignment }: { assignment: AssignmentOut }) {
  const rubric = useAsync(() => api.rubric(assignment.id).catch((cause) => {
    if (cause instanceof ApiError && cause.status === 404) return null;
    throw cause;
  }), [assignment.id]);
  const [title, setTitle] = useState("");
  const [rows, setRows] = useState<CriterionDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Once any submission exists, grades may reference the criteria: keep the structure.
  const structureLocked = Boolean(assignment.submission_count);

  useEffect(() => {
    const data: RubricOut | null = rubric.data ?? null;
    setTitle(data?.title ?? "Rubric");
    setRows(
      data?.criteria.map((c) => ({ id: c.id, key: c.key, label: c.label, description: c.description, max_points: String(c.max_points) })) ?? [
        { key: "overall", label: "Overall", description: "", max_points: String(assignment.max_points) },
      ],
    );
  }, [rubric.data, assignment.max_points]);

  if (rubric.loading) return <Loading label="Loading rubric…" />;
  if (rubric.error) return <ErrorBox error={rubric.error} retry={rubric.reload} />;

  const total = rows.reduce((sum, r) => sum + (Number(r.max_points) || 0), 0);
  const update = (index: number, patch: Partial<CriterionDraft>) =>
    setRows((cur) => cur.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  const move = (index: number, delta: number) =>
    setRows((cur) => {
      const next = [...cur];
      const [row] = next.splice(index, 1);
      next.splice(index + delta, 0, row);
      return next;
    });

  async function save() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.upsertRubric(assignment.id, {
        title,
        criteria: rows.map((r, position) => ({
          id: r.id,
          key: r.key,
          label: r.label,
          description: r.description,
          max_points: Number(r.max_points),
          position,
        })),
      });
      setMessage("Rubric saved");
      rubric.reload();
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.code === "RUBRIC_IN_USE"
          ? "Grades already use this rubric: you can rename criteria and change points, but not add or remove them."
          : errorMessage(cause),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack">
      <div className="spread">
        <h2 style={{ fontSize: 17, margin: 0 }}>Rubric</h2>
        <span className={`small ${total === assignment.max_points ? "dim" : ""}`} style={total === assignment.max_points ? undefined : { color: "var(--amber)" }}>
          Total {total} / {assignment.max_points} assignment points
        </span>
      </div>
      <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Rubric title" />
      {rows.map((row, index) => (
        <div key={row.id ?? `new-${index}`} className="rubric-row">
          <div className="stack-sm" style={{ flex: 1 }}>
            <input
              className="input"
              value={row.label}
              placeholder="Criterion"
              onChange={(e) => update(index, { label: e.target.value })}
            />
            <input
              className="input"
              value={row.description}
              placeholder="What earns full marks (shown to graders)"
              onChange={(e) => update(index, { description: e.target.value })}
            />
          </div>
          <input
            className="input"
            type="number"
            min={0}
            step="0.5"
            style={{ width: 90 }}
            value={row.max_points}
            onChange={(e) => update(index, { max_points: e.target.value })}
            aria-label="Points"
          />
          <div className="stack-sm">
            <button className="btn btn-ghost btn-sm" type="button" disabled={index === 0} onClick={() => move(index, -1)} aria-label="Move up">↑</button>
            <button className="btn btn-ghost btn-sm" type="button" disabled={index === rows.length - 1} onClick={() => move(index, 1)} aria-label="Move down">↓</button>
          </div>
          {!structureLocked && rows.length > 1 && (
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setRows((cur) => cur.filter((_, i) => i !== index))} aria-label="Remove criterion">
              ✕
            </button>
          )}
        </div>
      ))}
      {!structureLocked ? (
        <button
          className="btn btn-ghost btn-sm"
          style={{ alignSelf: "flex-start" }}
          type="button"
          onClick={() =>
            setRows((cur) => [
              ...cur,
              { key: slugKey("criterion", new Set(cur.map((r) => r.key))), label: "", description: "", max_points: "10" },
            ])
          }
        >
          + Add criterion
        </button>
      ) : (
        <span className="small dim">Students have submitted: criteria can be edited but not added or removed.</span>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
        {message && <Badge tone="green">{message}</Badge>}
        <button className="btn btn-primary" type="button" disabled={busy || rows.some((r) => !r.label.trim())} onClick={save}>
          Save rubric
        </button>
      </div>
    </section>
  );
}
