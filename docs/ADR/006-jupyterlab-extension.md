# ADR-006: JupyterLab extension for dataset insertion

**Status:** Accepted

## Context

ADR-005 says dataset selection inserts a code cell that must not execute. The
insertion has to happen in the **live** notebook the student has open, in
JupyterLab, so the cell appears immediately without a reload and without the
backend touching the file.

The web application and JupyterLab are different frontends on different
origins/routes (`/` and `/user/<name>/lab`). The catalogue is in the web app;
the notebook is in JupyterLab.

## Decision

Ship a **JupyterLab extension** (`jupyterlab-extension/`, package
`@opencs/jupyterlab-datasets`) that:

- adds an **OpenCS** menu with "Open dataset catalogue" and "Insert dataset
  cell";
- fetches the catalogue from the same public API
  (`GET /api/v1/datasets`, `credentials: "include"`), so the student's existing
  session cookie authorises it — no new auth path;
- inserts the returned snippet into the **active notebook** as a new code cell
  via the notebook tracker;
- **never executes** the inserted cell. The insert command rejects
  `auto_execute: true` as a contract violation.

The web application remains the catalogue's primary home. The extension exists
so the insertion happens in the live notebook; the two share the same API and
therefore the same published datasets and the same licence badges.

## Consequences

**Positive**

- Insertion happens in the live session: immediate, no reload, no backend file
  write race.
- One catalogue authority; the extension is a thin client of the public API.
- The non-execution rule is enforced in the one place that could violate it.

**Negative / costs**

- An extra artefact to build and install into the notebook image.
- A JupyterLab major-version upgrade may require extension updates; the
  package pins its `@jupyterlab/*` dependencies.
- The extension needs the web app's API reachable on the same origin (or CORS
  configured) — satisfied by the single-origin ingress.

## Alternatives considered

- **Backend writes the cell into the `.ipynb` file and the student reloads.**
  Rejected: racy, and the open editor would overwrite it.
- **A JupyterLab server extension that mutates documents.** Rejected: heavier
  than a frontend widget and still needs the same API call.
- **Server-side kernel execution of the snippet.** Rejected: violates ADR-005
  and HLD rule 8.
