import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { CourseOut } from "../../api/types";
import { useAuth } from "../../app/AuthContext";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { Modal, errorMessage } from "../../components/kit";

export const STAFF = new Set(["ta", "instructor", "admin", "staff"]);

export function isStaffRole(role: string | undefined): boolean {
  return role !== undefined && STAFF.has(role);
}

/** Teacher: classes I teach (+ create). Student: classes I take (+ join with a code). */
export function ClassesPage() {
  const { mode, user } = useAuth();
  const navigate = useNavigate();
  const courses = useAsync(() => api.courses(), []);
  const queue = useAsync(() => (mode === "teach" ? api.gradingQueue() : Promise.resolve(null)), [mode]);
  const [creating, setCreating] = useState(false);

  if (courses.loading) return <Loading label="Loading classes…" />;
  if (courses.error) return <ErrorBox error={courses.error} retry={courses.reload} />;

  const all = courses.data?.courses ?? [];
  const mine = all.filter((c) => (mode === "teach" ? isStaffRole(c.role_in_course) : c.role_in_course === "student"));
  const active = mine.filter((c) => c.status !== "archived");
  const archived = mine.filter((c) => c.status === "archived");
  const pending = new Map<string, number>();
  for (const item of queue.data?.items ?? []) {
    pending.set(item.course_id, (pending.get(item.course_id) ?? 0) + item.ungraded + item.drafts);
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>{mode === "teach" ? "Classes you teach" : "Your classes"}</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            {mode === "teach"
              ? "Post to the stream, manage classwork and grade submissions."
              : "Announcements, classwork and your returned feedback."}
          </p>
        </div>
        {mode === "teach" && user?.teaching?.can_create_courses && (
          <button className="btn btn-primary" type="button" onClick={() => setCreating(true)}>
            + Create class
          </button>
        )}
      </header>

      {mode === "learn" && <JoinClass onJoined={(course) => navigate(`/classes/${course.id}/stream`)} />}

      {active.length === 0 ? (
        <Empty title={mode === "teach" ? "No classes yet" : "You are not in any class yet"}>
          {mode === "teach" ? "Create a class to get started." : "Ask your teacher for a class code."}
        </Empty>
      ) : (
        <div className="grid grid-3">
          {active.map((course) => (
            <ClassCard key={course.id} course={course} pending={pending.get(course.id) ?? 0} />
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <details>
          <summary className="small dim">Archived classes ({archived.length})</summary>
          <div className="grid grid-3" style={{ marginTop: 12 }}>
            {archived.map((course) => (
              <ClassCard key={course.id} course={course} pending={0} />
            ))}
          </div>
        </details>
      )}

      {creating && (
        <CreateClass
          onClose={() => setCreating(false)}
          onCreated={(course) => navigate(`/classes/${course.id}/stream`)}
        />
      )}
    </div>
  );
}

function ClassCard({ course, pending }: { course: CourseOut; pending: number }) {
  return (
    <Link to={`/classes/${course.id}/stream`} className="card card-link class-card">
      <div className="spread">
        <span className="mono small dim">{course.code}</span>
        {course.status === "archived" ? (
          <Badge tone="neutral">archived</Badge>
        ) : (
          isStaffRole(course.role_in_course) && <Badge tone="accent">{course.role_in_course}</Badge>
        )}
      </div>
      <div className="class-card-title">{course.name}</div>
      <div className="spread small dim">
        <span>{course.term}</span>
        {pending > 0 && <Badge tone="amber">{pending} to grade</Badge>}
      </div>
    </Link>
  );
}

function JoinClass({ onJoined }: { onJoined: (course: CourseOut) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="card row"
      style={{ gap: 10, flexWrap: "wrap" }}
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        try {
          onJoined(await api.joinCourse(code.trim()));
        } catch (cause) {
          setError(errorMessage(cause).includes("not found") ? "That class code was not recognised." : errorMessage(cause));
        } finally {
          setBusy(false);
        }
      }}
    >
      <span className="small" style={{ fontWeight: 600 }}>Join a class</span>
      <input
        className="input mono"
        style={{ maxWidth: 160, textTransform: "uppercase" }}
        placeholder="Class code"
        value={code}
        maxLength={12}
        onChange={(e) => setCode(e.target.value)}
        aria-label="Class code"
      />
      <button className="btn btn-sm" type="submit" disabled={busy || code.trim().length < 4}>
        Join
      </button>
      {error && <span className="small" style={{ color: "var(--red)" }}>{error}</span>}
    </form>
  );
}

function CreateClass({ onClose, onCreated }: { onClose: () => void; onCreated: (course: CourseOut) => void }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [term, setTerm] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Create class" onClose={onClose}>
      <form
        className="stack"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            onCreated(await api.createCourse({ name, code, term, description }));
          } catch (cause) {
            setError(errorMessage(cause));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="field">
          <span className="label">Class name</span>
          <input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Data Wrangling" />
        </label>
        <div className="grid grid-2">
          <label className="field">
            <span className="label">Code</span>
            <input className="input mono" required value={code} onChange={(e) => setCode(e.target.value)} placeholder="DW-201" />
          </label>
          <label className="field">
            <span className="label">Term</span>
            <input className="input" required value={term} onChange={(e) => setTerm(e.target.value)} placeholder="2027 Spring" />
          </label>
        </div>
        <label className="field">
          <span className="label">Description (optional)</span>
          <textarea className="textarea" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {error && <div className="notice notice-error">{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
