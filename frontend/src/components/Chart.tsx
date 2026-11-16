import { useMemo } from "react";

interface ChartSpec {
  type: "scatter" | "bar" | "line";
  x: string;
  y: string;
  series?: string;
  data: Record<string, unknown>[];
}

const PALETTE = ["#5b8cff", "#35d0a0", "#f0b429", "#a78bfa", "#f2606b", "#38bdf8", "#fb923c"];

function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Minimal dependency-free chart renderer (SVG) for authored lesson visuals.
 * It draws only what the lesson content declares; it never executes code.
 */
export function Chart({ spec, title, caption }: { spec: ChartSpec; title: string; caption?: string }) {
  const width = 620;
  const height = 300;
  const pad = { top: 18, right: 22, bottom: 44, left: 52 };

  const seriesNames = useMemo(() => {
    if (!spec.series) return [null];
    const names = new Set<string>();
    for (const row of spec.data) names.add(String(row[spec.series] ?? ""));
    return [null, ...Array.from(names).sort()].slice(spec.series ? 1 : 0);
  }, [spec]);

  const points = useMemo(() => {
    const parsed: { x: number; y: number; group: string | null; raw: Record<string, unknown> }[] = [];
    for (const row of spec.data) {
      const x = numeric(row[spec.x]);
      const y = numeric(row[spec.y]);
      if (x === null || y === null) continue;
      parsed.push({ x, y, group: spec.series ? String(row[spec.series] ?? "") : null, raw: row });
    }
    return parsed;
  }, [spec]);

  const [xMin, xMax, yMin, yMax] = useMemo(() => {
    if (points.length === 0) return [0, 1, 0, 1];
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    let x0 = Math.min(...xs);
    let x1 = Math.max(...xs);
    let y0 = Math.min(...ys);
    let y1 = Math.max(...ys);
    const xPad = (x1 - x0) * 0.08 || 1;
    const yPad = (y1 - y0) * 0.08 || 1;
    x0 -= xPad;
    x1 += xPad;
    y0 = Math.min(0, y0 - yPad);
    y1 += yPad;
    return [x0, x1, y0, y1];
  }, [points]);

  if (points.length === 0) {
    return (
      <div className="card">
        <div className="dim">No plottable data for “{title}”.</div>
      </div>
    );
  }

  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const sx = (x: number) => pad.left + ((x - xMin) / (xMax - xMin)) * plotW;
  const sy = (y: number) => pad.top + plotH - ((y - yMin) / (yMax - yMin)) * plotH;

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => yMin + ((yMax - yMin) * i) / ticks);
  const xTicks = Array.from({ length: ticks + 1 }, (_, i) => xMin + ((xMax - xMin) * i) / ticks);

  const groups = seriesNames.length ? seriesNames : [null];

  // For bar charts, bucket by x value and average y per group.
  const bars = useMemo(() => {
    if (spec.type !== "bar") return [];
    const buckets = new Map<string, { x: number; totals: Map<string, { sum: number; n: number }> }>();
    for (const point of points) {
      const key = String(point.x);
      if (!buckets.has(key)) buckets.set(key, { x: point.x, totals: new Map() });
      const bucket = buckets.get(key)!;
      const group = point.group ?? "";
      const entry = bucket.totals.get(group) ?? { sum: 0, n: 0 };
      entry.sum += point.y;
      entry.n += 1;
      bucket.totals.set(group, entry);
    }
    return Array.from(buckets.values()).sort((a, b) => a.x - b.x);
  }, [points, spec.type]);

  return (
    <figure style={{ margin: 0 }}>
      <div className="card" style={{ padding: 14 }}>
        <div style={{ fontWeight: 650, marginBottom: 8 }}>{title}</div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={title}
          style={{ display: "block" }}
        >
          {yTicks.map((tick) => (
            <g key={`y-${tick}`}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={sy(tick)}
                y2={sy(tick)}
                stroke="#1d2942"
                strokeWidth={1}
              />
              <text x={pad.left - 8} y={sy(tick) + 4} textAnchor="end" fontSize={10} fill="#6b7a9b">
                {tick.toFixed(tick % 1 === 0 ? 0 : 1)}
              </text>
            </g>
          ))}
          {xTicks.map((tick) => (
            <text
              key={`x-${tick}`}
              x={sx(tick)}
              y={height - pad.bottom + 18}
              textAnchor="middle"
              fontSize={10}
              fill="#6b7a9b"
            >
              {tick.toFixed(tick % 1 === 0 ? 0 : 1)}
            </text>
          ))}
          <line x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} stroke="#2f4166" />
          <line x1={pad.left} x2={pad.left} y1={pad.top} y2={height - pad.bottom} stroke="#2f4166" />

          {spec.type === "scatter" &&
            groups.map((group, groupIndex) => (
              <g key={String(group)}>
                {points
                  .filter((point) => (group ? point.group === group : true))
                  .map((point, index) => (
                    <circle
                      key={index}
                      cx={sx(point.x)}
                      cy={sy(point.y)}
                      r={4.5}
                      fill={PALETTE[groupIndex % PALETTE.length]}
                      opacity={0.85}
                    />
                  ))}
              </g>
            ))}

          {spec.type === "line" &&
            groups.map((group, groupIndex) => {
              const filtered = points
                .filter((point) => (group ? point.group === group : true))
                .sort((a, b) => a.x - b.x);
              const d = filtered
                .map((point, index) => `${index === 0 ? "M" : "L"}${sx(point.x)},${sy(point.y)}`)
                .join(" ");
              return (
                <path
                  key={String(group)}
                  d={d}
                  fill="none"
                  stroke={PALETTE[groupIndex % PALETTE.length]}
                  strokeWidth={2}
                />
              );
            })}

          {spec.type === "bar" &&
            bars.map((bucket, bucketIndex) => {
              const groupKeys = Array.from(bucket.totals.keys());
              const slot = plotW / Math.max(bars.length, 1);
              const barW = (slot * 0.72) / Math.max(groupKeys.length, 1);
              return groupKeys.map((group, groupIndex) => {
                const entry = bucket.totals.get(group)!;
                const value = entry.sum / Math.max(entry.n, 1);
                const x = sx(bucket.x) - (slot * 0.72) / 2 + groupIndex * barW;
                const y = sy(value);
                return (
                  <rect
                    key={`${bucketIndex}-${group}`}
                    x={x}
                    y={y}
                    width={barW}
                    height={Math.max(1, height - pad.bottom - y)}
                    fill={PALETTE[groupIndex % PALETTE.length]}
                    rx={2}
                    opacity={0.9}
                  />
                );
              });
            })}

          {/* axis labels */}
          <text x={(pad.left + width - pad.right) / 2} y={height - 6} textAnchor="middle" fontSize={11} fill="#93a1bd">
            {spec.x}
          </text>
          <text
            x={14}
            y={(pad.top + height - pad.bottom) / 2}
            textAnchor="middle"
            fontSize={11}
            fill="#93a1bd"
            transform={`rotate(-90 14 ${(pad.top + height - pad.bottom) / 2})`}
          >
            {spec.y}
          </text>
        </svg>

        {spec.series && (
          <div className="row" style={{ marginTop: 10, gap: 14 }}>
            {groups.map((group, index) => (
              <span key={String(group)} className="row small muted" style={{ gap: 6 }}>
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 3,
                    background: PALETTE[index % PALETTE.length],
                    display: "inline-block",
                  }}
                />
                {String(group)}
              </span>
            ))}
          </div>
        )}
      </div>
      {caption && (
        <figcaption className="small dim" style={{ marginTop: 8 }}>
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
