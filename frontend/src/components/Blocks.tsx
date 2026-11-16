import type { Block, ContentStage } from "../api/types";
import { Chart } from "./Chart";

/** Very small inline formatter: **bold**, `code`, and *italic*. No HTML injection. */
function Inline({ text }: { text: string }) {
  const parts: (string | { kind: "code" | "bold" | "italic"; value: string })[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("`")) parts.push({ kind: "code", value: token.slice(1, -1) });
    else if (token.startsWith("**")) parts.push({ kind: "bold", value: token.slice(2, -2) });
    else parts.push({ kind: "italic", value: token.slice(1, -1) });
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));

  return (
    <>
      {parts.map((part, index) => {
        if (typeof part === "string") return <span key={index}>{part}</span>;
        if (part.kind === "code")
          return (
            <code key={index} className="inline-code">
              {part.value}
            </code>
          );
        if (part.kind === "bold") return <strong key={index}>{part.value}</strong>;
        return <em key={index}>{part.value}</em>;
      })}
    </>
  );
}

/** Renders markdown-ish prose: paragraphs, bullet lists, headings. */
function Prose({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let list: string[] = [];
  let paragraph: string[] = [];

  const flushList = () => {
    if (list.length === 0) return;
    nodes.push(
      <ul key={`ul-${nodes.length}`} style={{ margin: "0 0 10px", paddingLeft: 20, lineHeight: 1.65 }}>
        {list.map((item, index) => (
          <li key={index}>
            <Inline text={item} />
          </li>
        ))}
      </ul>,
    );
    list = [];
  };

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    nodes.push(
      <p key={`p-${nodes.length}`}>
        <Inline text={paragraph.join(" ")} />
      </p>,
    );
    paragraph = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    const listMatch = /^\s*[*-]\s+(.*)$/.exec(line);
    if (listMatch) {
      flushParagraph();
      list.push(listMatch[1]);
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      nodes.push(
        <div
          key={`h-${nodes.length}`}
          style={{
            fontWeight: 700,
            fontSize: level <= 2 ? 16 : 14,
            margin: "10px 0 6px",
            color: "var(--text)",
          }}
        >
          <Inline text={heading[2]} />
        </div>,
      );
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();

  return <div style={{ fontSize: 14.5 }}>{nodes}</div>;
}

function DataTable({
  columns,
  rows,
  caption,
}: {
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
  caption?: string;
}) {
  return (
    <figure style={{ margin: "0 0 6px" }}>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key}>{column.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td key={column.key}>{String(row[column.key] ?? "—")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && (
        <figcaption className="small dim" style={{ marginTop: 6 }}>
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "markdown":
      return <Prose text={block.text} />;
    case "callout":
      return (
        <div className={`callout callout-${block.variant}`}>
          {block.title && <div className="callout-title">{block.title}</div>}
          <Prose text={block.text} />
        </div>
      );
    case "code":
      return (
        <div className="stack-sm">
          {block.caption && <div className="small muted">{block.caption}</div>}
          <pre className="code-block">
            <code>{block.source}</code>
          </pre>
        </div>
      );
    case "output":
      if (block.kind === "table" && block.columns && block.rows) {
        return <DataTable columns={block.columns} rows={block.rows} />;
      }
      return (
        <div className="card" style={{ padding: 12 }}>
          <div className="small dim" style={{ marginBottom: 6 }}>
            Output
          </div>
          <pre className="code-block" style={{ background: "transparent", border: "none", padding: 0 }}>
            <code>{block.text ?? ""}</code>
          </pre>
        </div>
      );
    case "table":
      return <DataTable columns={block.columns} rows={block.rows} caption={block.caption} />;
    case "chart":
      return <Chart spec={block.spec} title={block.title} caption={block.caption} />;
    case "steps":
      return (
        <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
          {block.items.map((item, index) => (
            <li key={index} className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <span
                style={{
                  flex: "0 0 24px",
                  height: 24,
                  borderRadius: "50%",
                  background: "rgba(91,140,255,0.16)",
                  color: "var(--accent-strong)",
                  display: "grid",
                  placeItems: "center",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {index + 1}
              </span>
              <div>
                <div style={{ fontWeight: 650, fontSize: 13.5 }}>{item.title}</div>
                <div className="small muted">
                  <Inline text={item.text} />
                </div>
              </div>
            </li>
          ))}
        </ol>
      );
    case "mistakes":
      return (
        <div className="stack-sm">
          {block.items.map((item, index) => (
            <div key={index} className="card" style={{ padding: 13 }}>
              <div className="mono" style={{ color: "var(--red)", marginBottom: 4, fontSize: 12.5 }}>
                {item.error}
              </div>
              <div className="small" style={{ marginBottom: 4 }}>
                <Inline text={item.explanation} />
              </div>
              <div className="small">
                <span className="badge badge-green">Fix</span>{" "}
                <span className="muted">
                  <Inline text={item.fix} />
                </span>
              </div>
            </div>
          ))}
        </div>
      );
    case "checklist":
      return (
        <ul className="list-reset stack-sm">
          {block.items.map((item, index) => (
            <li key={index} className="row" style={{ gap: 9, alignItems: "flex-start" }}>
              <span style={{ color: "var(--green)", flex: "0 0 auto" }}>✓</span>
              <span className="small">
                <Inline text={item} />
              </span>
            </li>
          ))}
        </ul>
      );
    case "glossary":
      return (
        <dl style={{ margin: 0, display: "grid", gap: 8 }}>
          {block.items.map((item, index) => (
            <div key={index}>
              <dt style={{ fontWeight: 650, fontSize: 13.5 }}>{item.term}</dt>
              <dd className="small muted" style={{ margin: "0 0 0 0" }}>
                {item.definition}
              </dd>
            </div>
          ))}
        </dl>
      );
    default:
      return null;
  }
}

export function StageView({ stage }: { stage: ContentStage }) {
  return (
    <div className="stack">
      {stage.blocks.map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </div>
  );
}

export { Prose, Inline };
