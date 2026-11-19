import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import type { AttachmentInput, AttachmentKind, PostInput, PostOut, ReadersResponse } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Prose } from "../../components/Blocks";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import {
  ConfirmButton,
  MarkdownField,
  Modal,
  errorMessage,
  formatDateTime,
  fromLocalInput,
  relativeTime,
  toLocalInput,
} from "../../components/kit";
import { useCourse } from "./CourseShell";

/** The class stream (one-way: ADR-010). Staff post; everyone reads. */
export function StreamTab({ kind }: { kind?: "material" }) {
  const { course, isStaff } = useCourse();
  const archived = course.status === "archived";
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [extra, setExtra] = useState<PostOut[]>([]);
  const feed = useAsync(() => api.posts(course.id, { kind, limit: 20 }), [course.id, kind]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const location = useLocation();

  useEffect(() => {
    setNextCursor(feed.data?.next_cursor ?? null);
    setExtra([]);
  }, [feed.data]);

  // Deep link from a notification: /classes/:id/stream#post-<id>
  useEffect(() => {
    if (!location.hash || !feed.data) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [location.hash, feed.data]);

  async function loadMore() {
    if (!nextCursor) return;
    setCursor(nextCursor);
    const page = await api.posts(course.id, { kind, cursor: nextCursor, limit: 20 });
    setExtra((cur) => [...cur, ...page.posts]);
    setNextCursor(page.next_cursor);
  }

  const posts = [...(feed.data?.posts ?? []), ...extra];

  return (
    <div className="stream">
      {isStaff && !archived && (
        <Composer courseId={course.id} defaultKind={kind ?? "announcement"} onSaved={() => feed.reload()} />
      )}
      {feed.loading && <Loading label="Loading stream…" />}
      {feed.error && <ErrorBox error={feed.error} retry={feed.reload} />}
      {!feed.loading && posts.length === 0 && (
        <Empty title={kind ? "No materials yet" : "Nothing posted yet"}>
          {isStaff ? "Share an announcement or a resource with the class." : "Announcements from your teacher will appear here."}
        </Empty>
      )}
      {posts.map((post) => (
        <PostCard key={post.id} post={post} onChanged={() => feed.reload()} />
      ))}
      {nextCursor && (
        <button className="btn btn-ghost" type="button" onClick={loadMore} data-cursor={cursor}>
          Load older posts
        </button>
      )}
    </div>
  );
}

function PostCard({ post, onChanged }: { post: PostOut; onChanged: () => void }) {
  const { course, isStaff } = useCourse();
  const [editing, setEditing] = useState(false);
  const [readers, setReaders] = useState<ReadersResponse | null>(null);
  const marked = useRef(false);

  // Students: viewing a post marks it read (read receipts for the teacher).
  useEffect(() => {
    if (!isStaff && !post.is_read && !marked.current) {
      marked.current = true;
      void api.markPostRead(post.id).catch(() => undefined);
    }
  }, [isStaff, post.id, post.is_read]);

  if (editing) {
    return (
      <Composer
        courseId={course.id}
        existing={post}
        defaultKind={post.kind}
        onSaved={() => {
          setEditing(false);
          onChanged();
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const scheduled = post.status === "published" && post.publish_at && new Date(post.publish_at) > new Date();
  return (
    <article className={`card post${post.is_pinned ? " post-pinned" : ""}`} id={`post-${post.id}`}>
      <header className="spread" style={{ gap: 8, flexWrap: "wrap" }}>
        <div className="row" style={{ gap: 10 }}>
          <span className="avatar">{(post.author?.display_name ?? "?").slice(0, 1).toUpperCase()}</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13.5 }}>{post.author?.display_name ?? "Course staff"}</div>
            <div className="small dim">
              {relativeTime(post.publish_at ?? post.created_at)}
              {post.edited_at && " · edited"}
            </div>
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {post.kind === "material" && <Badge tone="accent">material</Badge>}
          {post.topic && <Badge tone="neutral">{post.topic}</Badge>}
          {post.is_pinned && <Badge tone="amber">pinned</Badge>}
          {post.status === "draft" && <Badge tone="purple">draft</Badge>}
          {scheduled && <Badge tone="purple">scheduled {formatDateTime(post.publish_at)}</Badge>}
        </div>
      </header>
      {post.title && <h3 className="post-title">{post.title}</h3>}
      {post.body.trim() && (
        <div className="post-body">
          <Prose text={post.body} />
        </div>
      )}
      {post.attachments.length > 0 && (
        <div className="attachments">
          {post.attachments.map((a) =>
            a.internal && a.url ? (
              <Link key={a.id} to={a.url} className="attachment">
                <span className="attachment-kind">{a.kind}</span>
                <span>{a.label}</span>
              </Link>
            ) : (
              <a key={a.id} href={a.url ?? "#"} className="attachment" target="_blank" rel="noopener noreferrer nofollow">
                <span className="attachment-kind">link ↗</span>
                <span>{a.label}</span>
              </a>
            ),
          )}
        </div>
      )}
      {isStaff && (
        <footer className="spread" style={{ marginTop: 10 }}>
          {post.status === "published" && post.published_at ? (
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={async () => setReaders(await api.postReaders(post.id))}
            >
              Seen by {post.read_count ?? 0} / {post.audience ?? 0}
            </button>
          ) : (
            <span className="small dim">Not visible to students yet</span>
          )}
          {post.can_edit && (
            <span className="row" style={{ gap: 6 }}>
              <button className="btn btn-sm" type="button" onClick={() => setEditing(true)}>
                Edit
              </button>
              <ConfirmButton
                label="Delete"
                confirmLabel="Delete post"
                danger
                onConfirm={async () => {
                  await api.deletePost(post.id);
                  onChanged();
                }}
              />
            </span>
          )}
        </footer>
      )}
      {readers && (
        <Modal title="Read receipts" onClose={() => setReaders(null)}>
          <div className="grid grid-2">
            <div>
              <div className="label">Seen ({readers.read.length})</div>
              <ul className="list-reset small">
                {readers.read.map((r) => (
                  <li key={r.user_id}>
                    {r.display_name} <span className="dim">· {relativeTime(r.read_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="label">Not yet ({readers.unread.length})</div>
              <ul className="list-reset small">
                {readers.unread.map((r) => (
                  <li key={r.user_id}>{r.display_name}</li>
                ))}
              </ul>
            </div>
          </div>
        </Modal>
      )}
    </article>
  );
}

const ATTACHMENT_LABELS: Record<AttachmentKind, string> = {
  link: "Web link",
  dataset: "Dataset",
  lesson: "Lesson",
  exercise: "Exercise",
  assignment: "Assignment",
};

function Composer({
  courseId,
  existing,
  defaultKind,
  onSaved,
  onCancel,
}: {
  courseId: string;
  existing?: PostOut;
  defaultKind: "announcement" | "material";
  onSaved: () => void;
  onCancel?: () => void;
}) {
  const [open, setOpen] = useState(Boolean(existing));
  const [kind, setKind] = useState<"announcement" | "material">(existing?.kind ?? defaultKind);
  const [title, setTitle] = useState(existing?.title ?? "");
  const [body, setBody] = useState(existing?.body ?? "");
  const [topic, setTopic] = useState(existing?.topic ?? "");
  const [pinned, setPinned] = useState(existing?.is_pinned ?? false);
  const [schedule, setSchedule] = useState(toLocalInput(existing?.publish_at));
  const [attachments, setAttachments] = useState<AttachmentInput[]>(
    existing?.attachments.map((a) => ({
      kind: a.kind as AttachmentKind,
      // Internal refs are re-sent by target: slug from the route, or the URL for links.
      target: a.kind === "link" ? a.url ?? "" : (a.url ?? "").split("/").pop() ?? "",
      label: a.label,
    })) ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button className="card composer-collapsed" type="button" onClick={() => setOpen(true)}>
        {defaultKind === "material" ? "Share a resource or notes with the class…" : "Announce something to your class…"}
      </button>
    );
  }

  async function submit(status: "draft" | "published") {
    setBusy(true);
    setError(null);
    const payload: PostInput = {
      kind,
      title,
      body,
      topic: topic.trim() || null,
      is_pinned: pinned,
      status,
      publish_at: fromLocalInput(schedule),
      attachments: attachments.filter((a) => a.target.trim()),
    };
    try {
      if (existing) await api.updatePost(existing.id, payload);
      else await api.createPost(courseId, payload);
      if (!existing) {
        setTitle("");
        setBody("");
        setTopic("");
        setPinned(false);
        setSchedule("");
        setAttachments([]);
        setOpen(false);
      }
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack composer">
      <div className="row" style={{ gap: 6 }}>
        {(["announcement", "material"] as const).map((k) => (
          <button
            key={k}
            type="button"
            className={`chip${kind === k ? " active" : ""}`}
            onClick={() => setKind(k)}
            disabled={Boolean(existing)}
          >
            {k === "announcement" ? "Announcement" : "Material / notes"}
          </button>
        ))}
      </div>
      <input
        className="input"
        placeholder={kind === "material" ? "Title (required)" : "Title (optional)"}
        value={title}
        maxLength={240}
        onChange={(e) => setTitle(e.target.value)}
      />
      <MarkdownField label="Message" value={body} onChange={setBody} rows={5} />
      <AttachmentEditor courseId={courseId} value={attachments} onChange={setAttachments} />
      <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
        <label className="field" style={{ minWidth: 180 }}>
          <span className="label">Topic (optional)</span>
          <input className="input" value={topic} maxLength={120} onChange={(e) => setTopic(e.target.value)} placeholder="Week 1" />
        </label>
        <label className="field">
          <span className="label">Schedule (optional)</span>
          <input className="input" type="datetime-local" value={schedule} onChange={(e) => setSchedule(e.target.value)} />
        </label>
        <label className="row small" style={{ gap: 6, alignSelf: "flex-end", paddingBottom: 8 }}>
          <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} /> Pin to top
        </label>
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <button
          className="btn btn-ghost"
          type="button"
          onClick={() => (onCancel ? onCancel() : setOpen(false))}
        >
          Cancel
        </button>
        <button className="btn" type="button" disabled={busy} onClick={() => submit("draft")}>
          Save draft
        </button>
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => submit("published")}>
          {schedule ? "Schedule" : existing?.status === "published" ? "Save" : "Post"}
        </button>
      </div>
    </div>
  );
}

function AttachmentEditor({
  courseId,
  value,
  onChange,
}: {
  courseId: string;
  value: AttachmentInput[];
  onChange: (value: AttachmentInput[]) => void;
}) {
  const datasets = useAsync(() => api.datasets({ limit: 100 }), []);
  const assignments = useAsync(() => api.assignments(courseId), [courseId]);
  const update = (index: number, patch: Partial<AttachmentInput>) =>
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  return (
    <div className="stack-sm">
      {value.map((item, index) => (
        <div key={index} className="row" style={{ gap: 6 }}>
          <select
            className="select"
            value={item.kind}
            onChange={(e) => update(index, { kind: e.target.value as AttachmentKind, target: "" })}
            aria-label="Attachment type"
          >
            {Object.entries(ATTACHMENT_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          {item.kind === "dataset" ? (
            <select className="select" style={{ flex: 1 }} value={item.target} onChange={(e) => update(index, { target: e.target.value })}>
              <option value="">Choose a dataset…</option>
              {(datasets.data?.datasets ?? []).map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.title}
                </option>
              ))}
            </select>
          ) : item.kind === "assignment" ? (
            <select className="select" style={{ flex: 1 }} value={item.target} onChange={(e) => update(index, { target: e.target.value })}>
              <option value="">Choose an assignment…</option>
              {(assignments.data?.assignments ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="input"
              style={{ flex: 1 }}
              value={item.target}
              placeholder={item.kind === "link" ? "https://…" : `${ATTACHMENT_LABELS[item.kind]} slug`}
              onChange={(e) => update(index, { target: e.target.value })}
            />
          )}
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => onChange(value.filter((_, i) => i !== index))} aria-label="Remove attachment">
            ✕
          </button>
        </div>
      ))}
      {value.length < 10 && (
        <button className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }} type="button" onClick={() => onChange([...value, { kind: "link", target: "" }])}>
          + Attach link or resource
        </button>
      )}
    </div>
  );
}
