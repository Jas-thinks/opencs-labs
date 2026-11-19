import { useMemo, useState } from "react";
import type { NotebookCell, NotebookDocument, NotebookOutput } from "../api/types";
import { Prose } from "./Blocks";

/**
 * Read-only renderer for a submitted notebook snapshot.
 *
 * Student output is untrusted. Nothing here ever injects raw HTML into the
 * grader's page:
 *  - markdown goes through the app's own renderer (no HTML interpretation);
 *  - images are <img> data URIs (scripts never run in an image context);
 *  - text/html (pandas tables, etc.) is shown in an iframe with sandbox="" -
 *    no scripts, no same-origin, no forms, no top navigation.
 */

const MAX_TEXT = 20_000;
const CELL_PAGE = 200;
const ANSI = /\u001b\[[0-9;?]*[A-Za-z]/g;
const BASE64 = /^[A-Za-z0-9+/=\s]+$/;

export function joinSource(source: string | string[] | undefined): string {
  if (source === undefined) return "";
  return Array.isArray(source) ? source.join("") : source;
}

export function stripAnsi(text: string): string {
  return text.replace(ANSI, "");
}

function LongText({ text, className }: { text: string; className: string }) {
  const [full, setFull] = useState(false);
  const clipped = !full && text.length > MAX_TEXT;
  return (
    <div>
      <pre className={className}>{clipped ? text.slice(0, MAX_TEXT) : text}</pre>
      {clipped && (
        <button className="btn btn-ghost btn-sm" type="button" onClick={() => setFull(true)}>
          Show all ({Math.round(text.length / 1024)} KB)
        </button>
      )}
    </div>
  );
}

export function SandboxedHtml({ html }: { html: string }) {
  const [tall, setTall] = useState(false);
  const doc = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font:13px system-ui,sans-serif;color:#e7ecf5;background:#0e1526;margin:8px}
    table{border-collapse:collapse}td,th{border:1px solid #2f4166;padding:3px 7px;text-align:right}
    th{background:#182241}</style></head><body>${html}</body></html>`;
  return (
    <div className="nb-html">
      <iframe
        title="Notebook HTML output"
        sandbox=""
        referrerPolicy="no-referrer"
        srcDoc={doc}
        style={{ height: tall ? 600 : 240 }}
      />
      <button className="btn btn-ghost btn-sm" type="button" onClick={() => setTall((v) => !v)}>
        {tall ? "Shrink" : "Expand"}
      </button>
    </div>
  );
}

function imageSrc(mime: string, data: string | string[]): string | null {
  const value = joinSource(data).trim();
  if (mime === "image/svg+xml") {
    // Rendered via <img>, so any script inside the SVG cannot execute.
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(value)}`;
  }
  if (!BASE64.test(value)) return null;
  return `data:${mime};base64,${value.replace(/\s+/g, "")}`;
}

export function OutputView({ output }: { output: NotebookOutput }) {
  if (output.output_type === "stream") {
    return (
      <LongText
        className={`nb-stream${output.name === "stderr" ? " nb-stderr" : ""}`}
        text={stripAnsi(joinSource(output.text))}
      />
    );
  }
  if (output.output_type === "error") {
    const trace = (output.traceback ?? []).map(stripAnsi).join("\n");
    return (
      <LongText
        className="nb-stream nb-stderr"
        text={trace || `${output.ename ?? "Error"}: ${output.evalue ?? ""}`}
      />
    );
  }
  const data = output.data ?? {};
  for (const mime of ["image/png", "image/jpeg", "image/gif", "image/svg+xml"]) {
    if (data[mime]) {
      const src = imageSrc(mime, data[mime]);
      if (src) return <img className="nb-image" src={src} alt="Notebook output" />;
    }
  }
  if (data["text/html"]) return <SandboxedHtml html={joinSource(data["text/html"])} />;
  if (data["text/markdown"]) return <Prose text={joinSource(data["text/markdown"])} />;
  if (data["text/plain"]) return <LongText className="nb-stream" text={stripAnsi(joinSource(data["text/plain"]))} />;
  const kinds = Object.keys(data);
  return kinds.length ? (
    <div className="small dim">[{kinds.join(", ")} output is not shown in this view]</div>
  ) : null;
}

function CellView({ cell, index }: { cell: NotebookCell; index: number }) {
  const source = joinSource(cell.source);
  if (cell.cell_type === "markdown") {
    return (
      <div className="nb-cell nb-markdown" id={`cell-${index}`}>
        <Prose text={source} />
      </div>
    );
  }
  if (cell.cell_type === "raw") {
    return (
      <div className="nb-cell" id={`cell-${index}`}>
        <pre className="nb-stream">{source}</pre>
      </div>
    );
  }
  const count = cell.execution_count ?? " ";
  return (
    <div className="nb-cell" id={`cell-${index}`}>
      <div className="nb-prompt">In [{count}]:</div>
      <pre className="nb-code">{source || " "}</pre>
      {(cell.outputs ?? []).length > 0 && (
        <div className="nb-outputs">
          {(cell.outputs ?? []).map((output, i) => (
            <OutputView key={i} output={output} />
          ))}
        </div>
      )}
    </div>
  );
}

export function NotebookView({ document }: { document: NotebookDocument }) {
  const cells = useMemo(() => document.cells ?? [], [document]);
  const [visible, setVisible] = useState(CELL_PAGE);
  if (cells.length === 0) {
    return <div className="empty">This notebook has no cells.</div>;
  }
  const codeCells = cells.filter((c) => c.cell_type === "code");
  const executed = codeCells.filter((c) => c.execution_count != null).length;
  return (
    <div className="nb">
      <div className="small dim" style={{ marginBottom: 8 }}>
        {cells.length} cells · {executed}/{codeCells.length} code cells executed
      </div>
      {cells.slice(0, visible).map((cell, index) => (
        <CellView key={index} cell={cell} index={index} />
      ))}
      {cells.length > visible && (
        <button className="btn btn-sm" type="button" onClick={() => setVisible((v) => v + CELL_PAGE)}>
          Show {Math.min(CELL_PAGE, cells.length - visible)} more cells
        </button>
      )}
    </div>
  );
}
