import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading, formatBytes, formatNumber, licenseTone } from "../../components/ui";

export function DatasetsHome() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");

  const categories = useAsync(() => api.datasetCategories(), []);
  const datasets = useAsync(
    () => api.datasets({ q: query || undefined, category: category || undefined, limit: 100 }),
    [query, category],
  );

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 680 }}>
          <h1>Dataset catalogue</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Centrally managed, versioned and checksummed. Every dataset is read-only and served
            locally — no runtime downloads from the internet.
          </p>
        </div>
      </header>

      <section className="card">
        <form
          className="row"
          style={{ gap: 10 }}
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(search.trim());
          }}
        >
          <input
            className="input"
            style={{ flex: "1 1 260px" }}
            placeholder="Search datasets…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="select"
            style={{ maxWidth: 240 }}
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="">All categories</option>
            {(categories.data ?? []).map((item) => (
              <option key={item.category} value={item.category}>
                {item.category} ({item.count})
              </option>
            ))}
          </select>
          <button className="btn" type="submit">
            Search
          </button>
        </form>
      </section>

      {datasets.loading && <Loading label="Loading datasets…" />}
      {datasets.error && <ErrorBox error={datasets.error} retry={datasets.reload} />}

      {datasets.data && (
        <div className="grid grid-2">
          {datasets.data.datasets.map((dataset) => (
            <Link key={dataset.slug} to={`/datasets/${dataset.slug}`} className="card card-link">
              <div className="spread" style={{ alignItems: "flex-start", marginBottom: 8 }}>
                <h2 style={{ fontSize: 16, marginBottom: 0 }}>{dataset.title}</h2>
                <Badge tone={licenseTone(dataset.license_status)}>
                  {dataset.license_status ?? "unknown licence"}
                </Badge>
              </div>
              <p className="small muted" style={{ marginBottom: 10 }}>
                {dataset.summary}
              </p>
              <div className="row small dim" style={{ gap: 12 }}>
                <span>{dataset.category}</span>
                {dataset.format && <span className="mono">{dataset.format}</span>}
                {dataset.row_count !== null && <span>{formatNumber(dataset.row_count)} rows</span>}
                {dataset.size_bytes !== null && <span>{formatBytes(dataset.size_bytes)}</span>}
              </div>
              {dataset.teaching_tags.length > 0 && (
                <div className="row" style={{ gap: 5, marginTop: 10 }}>
                  {dataset.teaching_tags.slice(0, 4).map((tag) => (
                    <span key={tag} className="badge badge-neutral">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}

      {datasets.data && datasets.data.datasets.length === 0 && (
        <div className="empty">No datasets match those filters.</div>
      )}
    </div>
  );
}
