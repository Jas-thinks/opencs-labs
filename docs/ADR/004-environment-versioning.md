# ADR-004: One pinned, immutable analytics environment

**Status:** Accepted

## Context

Lessons show output (a DataFrame, a chart, a number) and students reproduce it.
If a student's environment differs from the one the lesson was written against,
the lesson appears broken. Students must not be able to `pip install` into a
shared environment, and every library the curriculum requires must be present
and tested.

## Decision

**A single analytics image**, `opencs/analytics:1.0.0`, is the only execution
environment. It is:

- **pinned** — `notebook-image/requirements.lock` pins every dependency with
  `==`; the image tag is immutable in practice (rebuilding the same tag
  produces the same dependency set).
- **versioned** — `LABEL org.opencs.version` and the image tag record the
  release. The notebook metadata records `environment_image` so a notebook
  knows which environment it was created in.
- **tested** — `notebook-image/smoke-tests/` imports and exercises every
  required library (numpy, pandas, matplotlib, seaborn, plotly, scipy,
  statsmodels, scikit-learn, xgboost, openpyxl, pyarrow, fastparquet,
  sqlalchemy) in CI via `make test-env`.
- **shared** — notebooks, lesson activities, practice attempts and the grading
  sandbox all use this exact image, so "it worked in the lesson" and "it passes
  the checks" cannot diverge.

Students cannot modify it: the container filesystem for the environment is not
theirs to write, and `pip install` into a shared environment is an explicit
non-goal.

## Consequences

**Positive**

- Lesson output is reproducible: the same versions run for every student.
- Grading uses the same libraries as the lesson, eliminating a whole class of
  "works locally" failures.
- Upgrades are deliberate: bump `requirements.lock`, rebuild, re-run smoke
  tests, bump the tag.

**Negative / costs**

- A library upgrade requires an image rebuild and a new tag; there is no live
  upgrade path for a running class.
- Students who want an extra package cannot self-serve. This is a deliberate
  constraint; the supported path is an administrator adding it to the locked
  set.
- Every dataset change is decoupled from the image (see ADR-002), which keeps
  the image stable but means two artefacts to version.

## Alternatives considered

- **Let students install packages per session.** Rejected by the HLD: breaks
  reproducibility and widens the security surface.
- **Per-student or per-course environments.** Rejected for the first release:
  multiplies testing and image-build cost for no teaching benefit.
- **`latest` tags.** Rejected: silently changes behaviour under a student.
