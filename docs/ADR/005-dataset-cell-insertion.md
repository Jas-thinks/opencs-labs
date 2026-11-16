# ADR-005: Dataset insertion inserts a cell, it does not execute it

**Status:** Accepted

## Context

The headline workflow is: browse the dataset catalogue → click a dataset →
get a working DataFrame in the active notebook. It would be technically easy to
"helpfully" run the loading cell. That is the wrong behaviour:

- running code the student did not write or ask to run is surprising;
- it hides the code from the student, which defeats the teaching goal;
- it couples catalogue browsing to a live kernel, so browsing fails when the
  kernel is busy or stopped;
- it makes the inserted code unauditable — the student never sees what
  happened.

## Decision

**Insert, then let the student Run.**

- `GET /datasets/{slug}/snippet` returns
  `{ code, auto_execute: false, cell_type: "code", language: "python", path, read_only }`.
- The JupyterLab extension's insert command **constructs a new code cell and
  never calls `requestExecute`**. It rejects `auto_execute: true` outright as a
  contract violation.
- The web UI offers "Load cell snippet" (copy) and "Open in Notebook"; the copy
  explicitly states the cell will not run on its own.
- The snippet is a plain, readable `pd.read_csv(...)` + `df.head()` — the
  student can read and modify it.

The loading path is composed **server-side** from the dataset manifest and the
configured mount point. The browser cannot contribute a path segment.

## Consequences

**Positive**

- The student always sees the code that produces their data, which is the
  point.
- Catalogue browsing works with no kernel at all.
- No surprise side effects from a click.
- Path injection is impossible: the only variable is the dataset slug, which is
  resolved against published manifests.

**Negative / costs**

- One extra click for the student (browse → paste → run).
- The clip between insertion and execution means a student can insert a cell and
  forget to run it; the UI copy mitigates this.

## Alternatives considered

- **Auto-run on click.** Rejected for the reasons above and explicitly
  prohibited by HLD rule 8.
- **Backend writes directly into the notebook file.** Rejected: racy against
  the open editor, and it would not appear in the live notebook session.
- **A magic command (`%load_dataset iris`).** Rejected for the first release:
  it hides the code and requires a kernel-side extension.
