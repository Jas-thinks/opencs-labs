import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading, formatBytes, formatDate } from "../../components/ui";

export function NotebooksHome() {
  const server = useAsync(() => api.serverState(), []);
  const notebooks = useAsync(() => api.notebooks(), []);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("Untitled Notebook");

  function explain(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError) {
      if (cause.code === "UPSTREAM_UNAVAILABLE") {
        return "JupyterHub is not reachable from the backend. Start the hub and retry — no notebook data is lost.";
      }
      if (cause.code === "CAPACITY_EXHAUSTED") {
        return "All notebook slots are in use. Please try again shortly.";
      }
      return cause.message;
    }
    return fallback;
  }

  async function handleCreate() {
    setBusy("create");
    setError(null);
    try {
      const notebook = await api.createNotebook(title.trim() || "Untitled Notebook");
      const opened = await api.openNotebook(notebook.id);
      window.open(opened.url, "_blank", "noopener,noreferrer");
      notebooks.reload();
    } catch (cause) {
      setError(explain(cause, "Could not create the notebook."));
    } finally {
      setBusy(null);
    }
  }

  async function handleOpen(id: string) {
    setBusy(id);
    setError(null);
    try {
      const opened = await api.openNotebook(id);
      window.open(opened.url, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setError(explain(cause, "Could not open the notebook."));
    } finally {
      setBusy(null);
    }
  }

  async function handleRename(id: string, currentTitle: string) {
    const next = window.prompt("New notebook title", currentTitle);
    if (!next || next.trim() === currentTitle) return;
    setBusy(id);
    setError(null);
    try {
      await api.renameNotebook(id, next.trim());
      notebooks.reload();
    } catch (cause) {
      setError(explain(cause, "Could not rename the notebook."));
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Delete “${name}”? This removes the file from your workspace.`)) return;
    setBusy(id);
    setError(null);
    try {
      await api.deleteNotebook(id);
      notebooks.reload();
    } catch (cause) {
      setError(explain(cause, "Could not delete the notebook."));
    } finally {
      setBusy(null);
    }
  }

  const state = server.data;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 660 }}>
          <h1>Notebook workspace</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Your persistent JupyterLab environment. Files and outputs survive kernel restarts;
            nothing here is shared with another student.
          </p>
        </div>
        <div className="card" style={{ minWidth: 250 }}>
          <div className="spread">
            <span className="kpi-label">Notebook server</span>
            {state ? (
              <Badge tone={state.ready ? "green" : state.running ? "amber" : "neutral"}>
                {state.status}
              </Badge>
            ) : (
              <span className="small dim">unknown</span>
            )}
          </div>
          <p className="small dim" style={{ margin: "8px 0 10px" }}>
            {state?.ready
              ? "Running and ready. Launching opens JupyterLab in a new tab."
              : "Starts automatically the first time you open a notebook."}
          </p>
          <div className="row" style={{ gap: 6 }}>
            <button
              className="btn btn-sm"
              type="button"
              disabled={busy !== null}
              onClick={async () => {
                setBusy("server");
                setError(null);
                try {
                  await api.startServer();
                  server.reload();
                } catch (cause) {
                  setError(explain(cause, "Could not start the notebook server."));
                } finally {
                  setBusy(null);
                }
              }}
            >
              Start
            </button>
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              disabled={busy !== null}
              onClick={async () => {
                setBusy("server");
                setError(null);
                try {
                  await api.stopServer();
                  server.reload();
                } catch (cause) {
                  setError(explain(cause, "Could not stop the notebook server."));
                } finally {
                  setBusy(null);
                }
              }}
            >
              Stop
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={server.reload}>
              Refresh
            </button>
          </div>
        </div>
      </header>

      {error && <div className="notice notice-warn">{error}</div>}

      <section className="card">
        <div className="row" style={{ gap: 10 }}>
          <input
            className="input"
            style={{ flex: "1 1 240px" }}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="New notebook title"
          />
          <button className="btn btn-primary" type="button" onClick={handleCreate} disabled={busy !== null}>
            {busy === "create" ? <span className="spinner" /> : null}
            Create notebook
          </button>
        </div>
      </section>

      {notebooks.loading && <Loading label="Loading your notebooks…" />}
      {notebooks.error && <ErrorBox error={notebooks.error} retry={notebooks.reload} />}

      {notebooks.data && notebooks.data.notebooks.length === 0 && (
        <div className="empty">
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>No notebooks yet</div>
          Create one above, or launch a lesson or practice activity — it will open here too.
          <div style={{ marginTop: 14 }}>
            <Link to="/learn" className="btn btn-sm">
              Browse lessons
            </Link>
          </div>
        </div>
      )}

      {notebooks.data && notebooks.data.notebooks.length > 0 && (
        <div className="stack-sm">
          {notebooks.data.notebooks.map((notebook) => (
            <div key={notebook.id} className="card">
              <div className="spread" style={{ alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                    <span style={{ fontWeight: 650 }}>{notebook.title}</span>
                    <Badge tone={notebook.kind === "personal" ? "neutral" : "accent"}>
                      {notebook.kind}
                    </Badge>
                  </div>
                  <div className="small dim mono">{notebook.file_name}</div>
                  <div className="small dim" style={{ marginTop: 4 }}>
                    {formatBytes(notebook.size_bytes)} · updated {formatDate(notebook.updated_at)} ·{" "}
                    {notebook.environment_image}
                  </div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    type="button"
                    onClick={() => handleOpen(notebook.id)}
                    disabled={busy !== null}
                  >
                    {busy === notebook.id ? <span className="spinner" /> : null}
                    Open
                  </button>
                  <a className="btn btn-ghost btn-sm" href={api.downloadNotebookUrl(notebook.id)}>
                    Download
                  </a>
                  <button
                    className="btn btn-ghost btn-sm"
                    type="button"
                    onClick={() => handleRename(notebook.id, notebook.title)}
                    disabled={busy !== null}
                  >
                    Rename
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    type="button"
                    onClick={() => handleDelete(notebook.id, notebook.title)}
                    disabled={busy !== null}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
