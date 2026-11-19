import { useState } from "react";
import { api } from "../../api/client";
import type { MemberOut } from "../../api/types";
import { useAuth } from "../../app/AuthContext";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { ConfirmButton, errorMessage } from "../../components/kit";
import { useCourse } from "./CourseShell";

const ROLE_LABEL: Record<string, string> = { instructor: "Instructors", ta: "Teaching assistants", student: "Students" };

export function PeopleTab() {
  const { course, isInstructor, reload: reloadCourse } = useCourse();
  const { user } = useAuth();
  const members = useAsync(() => api.members(course.id), [course.id]);
  const [error, setError] = useState<string | null>(null);
  const archived = course.status === "archived";

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      members.reload();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  if (members.loading) return <Loading label="Loading people…" />;
  if (members.error) return <ErrorBox error={members.error} retry={members.reload} />;
  const groups = new Map<string, MemberOut[]>();
  for (const m of members.data?.members ?? []) groups.set(m.role_in_course, [...(groups.get(m.role_in_course) ?? []), m]);

  return (
    <div className="stack" style={{ gap: 18, maxWidth: 900 }}>
      {isInstructor && !archived && (
        <div className="grid grid-2" style={{ alignItems: "start" }}>
          <AddPeople onAdded={() => members.reload()} />
          <JoinCodeCard onChanged={reloadCourse} />
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      {["instructor", "ta", "student"].map((role) => (
        <section key={role} className="card" style={{ padding: 0 }}>
          <div className="spread" style={{ padding: "12px 16px" }}>
            <h2 style={{ fontSize: 15, margin: 0 }}>{ROLE_LABEL[role]}</h2>
            <span className="small dim">{groups.get(role)?.length ?? 0}</span>
          </div>
          {(groups.get(role) ?? []).map((m) => (
            <div key={m.user_id} className="work-row">
              <div className="row" style={{ gap: 10 }}>
                <span className="avatar">{m.display_name.slice(0, 1).toUpperCase()}</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                    {m.display_name} {m.user_id === user?.id && <Badge tone="neutral">you</Badge>}
                  </div>
                  <div className="small dim">{m.email}</div>
                </div>
              </div>
              {isInstructor && !archived && (
                <div className="row" style={{ gap: 6 }}>
                  <select
                    className="select"
                    value={m.role_in_course}
                    onChange={(e) => run(() => api.updateMemberRole(course.id, m.user_id, e.target.value))}
                    aria-label={`Role for ${m.display_name}`}
                  >
                    <option value="student">Student</option>
                    <option value="ta">TA</option>
                    <option value="instructor">Instructor</option>
                  </select>
                  <ConfirmButton
                    label="Remove"
                    confirmLabel="Remove from class"
                    danger
                    onConfirm={() => run(() => api.removeMember(course.id, m.user_id))}
                  />
                </div>
              )}
            </div>
          ))}
          {(groups.get(role)?.length ?? 0) === 0 && <div className="small dim" style={{ padding: "0 16px 14px" }}>Nobody yet.</div>}
        </section>
      ))}
    </div>
  );
}

function AddPeople({ onAdded }: { onAdded: () => void }) {
  const { course } = useCourse();
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState("student");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="card stack">
      <h2 style={{ fontSize: 15, margin: 0 }}>Add people</h2>
      <textarea
        className="textarea"
        rows={4}
        placeholder={"One email per line, or paste a list\nana@school.edu, ben@school.edu"}
        value={emails}
        onChange={(e) => setEmails(e.target.value)}
      />
      <div className="row" style={{ gap: 8 }}>
        <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="student">as students</option>
          <option value="ta">as TAs</option>
          <option value="instructor">as instructors</option>
        </select>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy || !emails.trim()}
          onClick={async () => {
            setBusy(true);
            setError(null);
            setResult(null);
            try {
              const list = emails.split(/[\s,;]+/).filter(Boolean);
              const r = await api.addMembers(course.id, list, role);
              const parts = [`${r.added.length} added`, `${r.updated.length} updated`];
              if (r.unknown.length) parts.push(`no account for: ${r.unknown.join(", ")}`);
              setResult(parts.join(" · "));
              setEmails(r.unknown.join("\n"));
              onAdded();
            } catch (cause) {
              setError(errorMessage(cause));
            } finally {
              setBusy(false);
            }
          }}
        >
          Add
        </button>
      </div>
      {result && <div className="notice notice-info small">{result}</div>}
      {error && <div className="notice notice-error">{error}</div>}
    </section>
  );
}

function JoinCodeCard({ onChanged }: { onChanged: () => void }) {
  const { course } = useCourse();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card stack">
      <h2 style={{ fontSize: 15, margin: 0 }}>Class code</h2>
      {course.join_code ? (
        <>
          <div className="join-code-big mono">{course.join_code}</div>
          <span className="small dim">Students enter this on their Classes page to join as students.</span>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => navigator.clipboard?.writeText(course.join_code ?? "")}>
              Copy
            </button>
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => run(() => api.rotateJoinCode(course.id))}>
              Reset code
            </button>
            <button className="btn btn-sm btn-ghost" type="button" disabled={busy} onClick={() => run(() => api.disableJoinCode(course.id))}>
              Turn off
            </button>
          </div>
        </>
      ) : (
        <>
          <span className="small dim">Self-enrolment is off. Turn it on to give students a code.</span>
          <button className="btn btn-sm" style={{ alignSelf: "flex-start" }} type="button" disabled={busy} onClick={() => run(() => api.rotateJoinCode(course.id))}>
            Create class code
          </button>
        </>
      )}
      {error && <div className="notice notice-error">{error}</div>}
    </section>
  );
}
