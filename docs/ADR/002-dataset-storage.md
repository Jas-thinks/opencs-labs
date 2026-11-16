# ADR-002: Dataset storage — MinIO plus a read-only serving tree

**Status:** Accepted

## Context

Lessons and exercises reference a fixed library of teaching datasets (Iris,
Titanic, wine quality, California housing, Palmer penguins, diabetes, tips,
gapminder, NYC taxi sample, retail sales). The requirements are:

- datasets are centrally managed and **read-only** to students
- common datasets are served **locally**, never downloaded at runtime
- **versions and checksums** are tracked
- notebook code reads the dataset by a stable path inside the student's kernel
- the same bytes are used by lessons, practice and automated grading

## Decision

Three-layer storage:

1. **Raw sources** — `datasets/raw/` (gitignored). Reproducible via
   `scripts/fetch_datasets.py`, which records a normalisation step per source.
2. **Manifests** — `datasets/manifests/<slug>.json`. Each records, per version:
   format, relative mount path, sha256, size, row count, column schema, a
   preview, and the licence/attribution. The manifest is the contract.
3. **Serving tree** — `datasets/serving/<slug>/v<n>/<file>`. This exact tree is:
   - uploaded unchanged to **MinIO** (S3-compatible), keyed by `object_key`,
     with the sha256 stored as object metadata (`scripts/sync_datasets.py`);
   - materialised on a **read-only volume** mounted at
     `/opt/opencs/datasets` inside every notebook pod and every grading
     container.

Dataset loading cells read `pd.read_csv("/opt/opencs/datasets/iris/v1/iris.csv")`
— the path is composed server-side from the manifest, never from browser input.

## Consequences

**Positive**

- One source of truth (the manifest) drives the catalogue, the preview, the
  snippet and verification.
- Immutability: a content change is a new version directory, so a pinned lesson
  never breaks underneath a student.
- Integrity is checked three times: at fetch, at seed (refuses to publish on
  mismatch), and at sync (re-verifies before upload).
- Object storage gives a durable copy independent of the volume.

**Negative / costs**

- Every dataset must be fetched and verified before first run; the artefacts
  are not in git.
- The serving tree must be present on the node that runs notebooks, so it is a
  ReadWriteMany PVC (or a per-node hostPath) rather than object storage being
  read directly. This is deliberate: a low-latency local read is what makes
  `pd.read_csv` in a lesson feel instant.
- Licence verification is per dataset. Datasets whose upstream licence is
  unclear are marked `license_status: review-required` and surfaced as such in
  the UI; they must be confirmed before production use.

## Alternatives considered

- **Students download from Kaggle / public mirrors at runtime.** Rejected by
  the HLD: slow, unreliable, and a supply-chain risk in a teaching environment.
- **Serve datasets from S3/MinIO directly inside notebook code.** Rejected:
  leaks credentials into the student namespace and adds network latency.
- **Bake datasets into the notebook image.** Rejected: coupling content to the
  image makes a dataset update an image rebuild and thickens the image for
  every user.
