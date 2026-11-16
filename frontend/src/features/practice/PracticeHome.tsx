import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAsync } from "../../app/useAsync";
import { Badge, ErrorBox, Loading, Progress, difficultyTone } from "../../components/ui";

const difficulties = ["", "Easy", "Medium", "Hard"];

export function PracticeHome() {
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");

  const topics = useAsync(() => api.exerciseTopics(), []);
  const progress = useAsync(() => api.practiceProgress(), []);
  const exercises = useAsync(
    () => api.exercises({ topic: topic || undefined, difficulty: difficulty || undefined, q: query || undefined }),
    [topic, difficulty, query],
  );

  return (
    <div className="stack" style={{ gap: 22 }}>
      <header className="page-head" style={{ marginBottom: 0 }}>
        <div style={{ maxWidth: 680 }}>
          <h1>Practice</h1>
          <p className="lead" style={{ marginBottom: 0 }}>
            Hands-on exercises in your own isolated notebook. Each one opens the pinned analytics
            environment with starter code — you write, run and submit.
          </p>
        </div>
        {progress.data && (
          <div className="card" style={{ minWidth: 220 }}>
            <div className="kpi">
              <span className="kpi-label">Exercises completed</span>
              <span className="kpi-value">
                {progress.data.completed_exercises}
                <span className="small dim" style={{ fontWeight: 500 }}>
                  {" "}
                  / {progress.data.total_exercises}
                </span>
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              <Progress
                percent={
                  progress.data.total_exercises
                    ? Math.round(
                        (progress.data.completed_exercises / progress.data.total_exercises) * 100,
                      )
                    : 0
                }
              />
            </div>
          </div>
        )}
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
            style={{ flex: "1 1 220px" }}
            placeholder="Search exercises…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select className="select" style={{ maxWidth: 200 }} value={topic} onChange={(event) => setTopic(event.target.value)}>
            <option value="">All topics</option>
            {(topics.data ?? []).map((item) => (
              <option key={item.topic} value={item.topic}>
                {item.topic} ({item.count})
              </option>
            ))}
          </select>
          <select
            className="select"
            style={{ maxWidth: 150 }}
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value)}
          >
            {difficulties.map((level) => (
              <option key={level} value={level}>
                {level || "All levels"}
              </option>
            ))}
          </select>
          <button className="btn" type="submit">
            Search
          </button>
        </form>
      </section>

      {exercises.loading && <Loading label="Loading exercises…" />}
      {exercises.error && <ErrorBox error={exercises.error} retry={exercises.reload} />}

      {exercises.data && (
        <>
          <div className="spread">
            <span className="small dim">
              {exercises.data.total} exercise{exercises.data.total === 1 ? "" : "s"}
            </span>
          </div>
          <div className="grid grid-2">
            {exercises.data.exercises.map((exercise) => (
              <Link key={exercise.slug} to={`/practice/${exercise.slug}`} className="card card-link">
                <div className="spread" style={{ alignItems: "flex-start", marginBottom: 8 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <Badge tone={difficultyTone(exercise.difficulty)}>{exercise.difficulty}</Badge>
                    <Badge tone="neutral">{exercise.topic}</Badge>
                    {exercise.completed && <Badge tone="green">Completed</Badge>}
                  </div>
                  <span className="small dim">{exercise.estimated_minutes} min</span>
                </div>
                <h2 style={{ fontSize: 16, marginBottom: 4 }}>{exercise.title}</h2>
                <p className="small muted" style={{ marginBottom: 10 }}>
                  {exercise.objective}
                </p>
                <div className="row small dim" style={{ gap: 12 }}>
                  {exercise.has_automated_checks && <span>✓ Automated checks</span>}
                  {exercise.attempts > 0 && (
                    <span>
                      {exercise.attempts} attempt{exercise.attempts === 1 ? "" : "s"}
                    </span>
                  )}
                  {exercise.dataset_slugs.length > 0 && <span>{exercise.dataset_slugs.join(", ")}</span>}
                </div>
              </Link>
            ))}
          </div>
          {exercises.data.exercises.length === 0 && (
            <div className="empty">No exercises match those filters.</div>
          )}
        </>
      )}
    </div>
  );
}
