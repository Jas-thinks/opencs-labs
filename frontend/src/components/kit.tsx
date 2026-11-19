import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { Prose } from "./Blocks";

/** Route-driven tabs (each tab is a URL, so tabs are linkable and back-button safe). */
export function RouteTabs({ tabs }: { tabs: { to: string; label: string; badge?: number }[] }) {
  return (
    <nav className="tabs" aria-label="Sections">
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
          {tab.label}
          {tab.badge ? <span className="tab-badge">{tab.badge}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal card${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: 17, margin: 0 }}>{title}</h2>
          <button className="btn btn-ghost btn-sm" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** A button that asks for confirmation inline before doing something destructive. */
export function ConfirmButton({
  label,
  confirmLabel = "Confirm",
  onConfirm,
  danger = false,
  disabled = false,
}: {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  danger?: boolean;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!asking) {
    return (
      <button className={`btn btn-sm${danger ? " btn-danger" : ""}`} type="button" disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="row" style={{ gap: 6 }}>
      <button
        className={`btn btn-sm ${danger ? "btn-danger" : "btn-primary"}`}
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setAsking(false);
          }
        }}
      >
        {busy ? "Working…" : confirmLabel}
      </button>
      <button className="btn btn-ghost btn-sm" type="button" onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
  );
}

/** Textarea with a Write/Preview toggle using the app's safe markdown renderer. */
export function MarkdownField({
  label,
  value,
  onChange,
  rows = 6,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [preview, setPreview] = useState(false);
  return (
    <div className="field">
      <div className="spread">
        <span className="label">{label}</span>
        <span className="row" style={{ gap: 4 }}>
          <button className={`btn btn-ghost btn-sm${!preview ? " is-on" : ""}`} type="button" onClick={() => setPreview(false)}>
            Write
          </button>
          <button className={`btn btn-ghost btn-sm${preview ? " is-on" : ""}`} type="button" onClick={() => setPreview(true)}>
            Preview
          </button>
        </span>
      </div>
      {preview ? (
        <div className="card md-preview">{value.trim() ? <Prose text={value} /> : <span className="dim small">Nothing to preview.</span>}</div>
      ) : (
        <textarea className="textarea" rows={rows} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      )}
      <span className="small dim">Supports **bold**, *italic*, `code`, # headings and - lists.</span>
    </div>
  );
}

// --- dates ----------------------------------------------------------------
/** ISO (UTC) -> value for <input type="datetime-local"> in the user's timezone. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** <input type="datetime-local"> value (local time) -> ISO UTC, or null when empty. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "";
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.round(diff / 60000);
  if (Math.abs(minutes) < 1) return "just now";
  if (minutes < 60 && minutes > 0) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24 && hours > 0) return `${hours} h ago`;
  return formatDateTime(value);
}

export function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}
