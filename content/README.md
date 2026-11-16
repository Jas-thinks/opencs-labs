# Curriculum content

Authored teaching content, validated in CI and loaded into the database by
`scripts/seed.py`.

```
content/
├── paths.json        the learning path → module ordering
├── lessons/          one YAML file per module, containing its lessons
└── exercises/        one YAML file per exercise
```

## Lesson structure

Every lesson must contain the **seven stages**, each an ordered list of blocks:

| Stage | Purpose |
|---|---|
| `explore` | Meet the data or the problem |
| `understand` | Explain the concept, no unexplained jumps |
| `inspect` | Look at the actual values/shape |
| `execute` | Run code and see output |
| `visualize` | See the result as a chart |
| `debug` | Common errors and how to fix them |
| `practice` | Checklist and pointer to the exercise |

`scripts/validate_content.py` enforces this; a missing stage fails CI.

### Block types

`markdown`, `code`, `output`, `table`, `chart`, `callout`, `steps`,
`mistakes`, `checklist`, `dataset`, `glossary`.

Charts declare their data inline under `spec` (`type`, `x`, `y`, `series`,
`data`). The frontend renders them as SVG — no plotting library, no code
execution.

A lesson may also carry a `notebook_activity` with `cells`, which becomes the
notebook the student opens from **Open in Notebook**.

## Exercise structure

```yaml
slug: pandas-select-iris
title: Select and Derive in Iris
topic: Pandas
difficulty: Medium          # Easy | Medium | Hard
estimated_minutes: 18
datasets: [iris]
related_lesson: pandas-series-and-dataframes
objective: ...
instructions:
  markdown: |
    ...
starter_notebook:
  intro_markdown: |
    ...
  cells:
    - source: |
        import pandas as pd
        df = pd.read_csv("/opt/opencs/datasets/iris/v1/iris.csv")
hints:
  - "..."
evaluation:
  type: python_assertions
  timeout_seconds: 60
  tests:
    - id: filtered-frame
      description: ...
      code: |
        assert long is not None
```

### Evaluation rules

- `tests[].code` runs after all notebook cells, in the same namespace, inside
  the grading sandbox — never in the API process.
- `solution_code` is **never serialised** through the API. The validator warns
  if it is present so it stays server-side only.
- `timeout_seconds` bounds each test.
- An exercise without `tests` is instructor-assessed; the API returns
  `409 NO_AUTOMATED_CHECKS` if a student requests evaluation.

## Rules

1. No unexplained jumps — assume the previous lesson was read.
2. Every lesson ends with something the student can run.
3. Dataset paths in code use `/opt/opencs/datasets/...` (the read-only mount).
4. Content is versioned in git; the database is reseeded from it.

## Validate

```bash
make validate     # or: python scripts/validate_content.py
```
