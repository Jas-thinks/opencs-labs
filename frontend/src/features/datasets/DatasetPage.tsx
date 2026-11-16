import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import {
  Badge,
  ErrorBox,
  Loading,
  formatBytes,
  formatDate,
  formatNumber,
  licenseTone,
} from "../../components/ui";
import type { SnippetResponse } from "../../api/types";

export function DatasetPage() {
  const { datasetSlug = "" } = useParams();
  const { data, loading, error, reload } = useAsync(() => api.dataset(datasetSlug), [datasetSlug]);
  const preview = useAsync(() => api.datasetPreview(datasetSlug, 20), [datasetSlug]);

  const [snippet, setSnippet] = useState<SnippetResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleSnippet() {
    setNotice(null);
    try {
      const result = await api.datasetSnippet(datasetSlug);
      setSnippet(result);
    } catch (cause) {
      setNotice(cause instanceof ApiError ? cause.message : "Could not build the loading snippet.");
    }
  }

  async function handleCopy() {
    if (!snippet) return;
    try {
      await navigator.clipboard.writeText(snippet.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setNotice("Clipboard access was blocked. Select the code and copy it manually.");
    }
  }

  async function handleOpenNotebook() {
    setNotice(null);
    try {
      const notebook = await api.createNotebook(`${data?.title ?? "Dataset"} analysis`);
      const opened = await api.openNotebook(notebook.id);
      window.open(opened.url, "_blank", "noopener,noreferrer");
      setNotice(
        "Notebook opened. Paste the snippet into a new cell, then run it yourself — the platform never executes dataset code automatically.",
      );
    } catch (cause) {
      setNotice(
        cause instanceof ApiError && cause.code === "UPSTREAM_UNAVAILABLE"
          ? "The notebook service is unavailable. You can still copy the snippet."
          : "Could not open a notebook for this dataset.",
      );
    }
  }

  if (loading) return <Loading label="Loading dataset…" />;
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return null;

  const current = data.versions.find((version) => version.is_current) ?? data.versions[0];

  return (
    <div className="stack" style={{ gap: 20 }}>
      <nav className="small dim row" style={{ gap: 6 }}>
        <Link to="/datasets">Datasets</Link>
        <span>/</span>
        <span style={{ color: "var(--text)" }}>{data.title}</span>
      </nav>

      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 720 }}>
          <div className="row" style={{ gap: 6, marginBottom: 8 }}>
            <Badge tone="neutral">{data.category}</Badge>
            <Badge tone={licenseTone(data.license_status)}>{data.license_status ?? "licence unknown"}</Badge>
            <Badge tone="green">Read-only</Badge>
            {data.version !== null && <Badge tone="accent">v{data.version}</Badge>}
          </div>
          <h1>{data.title}</h1>
          <p className="lead">{data.description}</p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn btn-primary" type="button" onClick={handleOpenNotebook}>
            Open in Notebook
          </button>
          <button className="btn" type="button" onClick={handleSnippet}>
            Load cell snippet
          </button>
        </div>
      </header>

      {notice && <div className="notice notice-info">{notice}</div>}

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 320px", alignItems: "start" }}>
        <div className="stack">
          <section className="card">
            <div className="spread" style={{ marginBottom: 10 }}>
              <h2 style={{ marginBottom: 0 }}>Sample rows</h2>
              {preview.data && (
                <span className="small dim">
                  showing {preview.data.rows.length} of {formatNumber(preview.data.row_count)} rows
                </span>
              )}
            </div>
            {preview.loading && <Loading label="Loading preview…" />}
            {preview.error && <ErrorBox error={preview.error} retry={preview.reload} />}
            {preview.data && (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      {preview.data.columns.map((column) => (
                        <th key={column.name}>
                          {column.name}
                          <span className="dim" style={{ fontWeight: 400, textTransform: "none", marginLeft: 6 }}>
                            {column.dtype}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.data.rows.map((row, index) => (
                      <tr key={index}>
                        {preview.data!.columns.map((column) => (
                          <td key={column.name}>{row[column.name] === null ? "—" : String(row[column.name])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {snippet && (
            <section className="card stack-sm">
              <div className="spread">
                <h2 style={{ marginBottom: 0 }}>Loading cell</h2>
                <div className="row" style={{ gap: 6 }}>
                  <Badge tone={snippet.auto_execute ? "red" : "green"}>
                    {snippet.auto_execute ? "auto-run (unexpected)" : "never auto-runs"}
                  </Badge>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={handleCopy}>
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
              </div>
              <p className="small muted">
                Paste this into a new cell in your notebook, then run it yourself. The platform
                inserts code — it never executes it for you.
              </p>
              <pre className="code-block">
                <code>{snippet.code}</code>
              </pre>
              <div className="small dim mono">{snippet.path}</div>
            </section>
          )}

          {data.notes && (
            <div className="notice notice-warn">
              <strong>Notes:</strong> {data.notes}
            </div>
          )}
        </div>

        <aside className="stack">
          <section className="card stack-sm">
            <h2 style={{ marginBottom: 4 }}>Details</h2>
            <dl style={{ margin: 0, display: "grid", gap: 8 }}>
              <div className="spread">
                <dt className="small dim">Rows</dt>
                <dd className="small" style={{ margin: 0 }}>
                  {formatNumber(current?.row_count ?? data.row_count)}
                </dd>
              </div>
              <div className="spread">
                <dt className="small dim">Format</dt>
                <dd className="small mono" style={{ margin: 0 }}>
                  {current?.format ?? data.format ?? "—"}
                </dd>
              </div>
              <div className="spread">
                <dt className="small dim">Size</dt>
                <dd className="small" style={{ margin: 0 }}>
                  {formatBytes(current?.size_bytes ?? data.size_bytes)}
                </dd>
              </div>
              <div className="spread">
                <dt className="small dim">Columns</dt>
                <dd className="small" style={{ margin: 0 }}>
                  {data.columns.length}
                </dd>
              </div>
              <div className="spread">
                <dt className="small dim">Version</dt>
                <dd className="small" style={{ margin: 0 }}>
                  {current?.version ?? data.version ?? "—"}
                </dd>
              </div>
            </dl>
          </section>

          <section className="card stack-sm">
            <h2 style={{ marginBottom: 4 }}>Columns</h2>
            <ul className="list-reset stack-sm">
              {data.columns.map((column) => (
                <li key={column.name} className="spread">
                  <span className="small mono">{column.name}</span>
                  <span className="small dim">{column.dtype}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="card stack-sm">
            <h2 style={{ marginBottom: 4 }}>Licence & attribution</h2>
            <div className="small">
              <strong>{data.license ?? "Not stated"}</strong>
            </div>
            <p className="small muted" style={{ marginBottom: 4 }}>
              {data.attribution}
            </p>
            {data.source_url && (
              <a className="small" href={data.source_url} target="_blank" rel="noreferrer">
                Original source ↗
              </a>
            )}
            {data.license_url && (
              <a className="small" href={data.license_url} target="_blank" rel="noreferrer">
                Licence terms ↗
              </a>
            )}
          </section>

          {data.versions.length > 0 && (
            <section className="card stack-sm">
              <h2 style={{ marginBottom: 4 }}>Versions</h2>
              {data.versions.map((version) => (
                <div key={version.version} className="stack-sm" style={{ gap: 2 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <Badge tone={version.is_current ? "green" : "neutral"}>v{version.version}</Badge>
                    <span className="small">{version.format}</span>
                    {version.is_current && <span className="small dim">current</span>}
                  </div>
                  <div className="small dim">
                    {formatDate(version.published_at)} · {formatBytes(version.size_bytes)}
                  </div>
                  <div className="small dim mono" style={{ wordBreak: "break-all" }}>
                    sha256 {version.sha256.slice(0, 16)}…
                  </div>
                </div>
              ))}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
