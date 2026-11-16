# Dataset library

Canonical teaching datasets for OpenCS Labs. Everything here is centrally
managed, versioned and read-only to students.

## Layout

```
datasets/
├── raw/            downloaded sources (gitignored; reproducible via scripts)
├── serving/        the published, read-only tree mounted into notebooks
│   └── <slug>/v1/  one directory per dataset version (+ manifest.json)
└── manifests/      one JSON manifest per dataset + index.json
```

## Lifecycle

1. **Fetch and verify** — `make fetch-datasets`
   (`scripts/fetch_datasets.py`) downloads each source, normalises it, records
   the sha256, row count, column schema and a preview into
   `datasets/manifests/<slug>.json`.
2. **Verify integrity** — the manifest holds the sha256 of the exact bytes in
   `serving/`. `scripts/seed.py` refuses to publish a dataset whose file does
   not match its recorded checksum.
3. **Publish** — `make sync-datasets` (`scripts/sync_datasets.py`) re-verifies
   every file and uploads unchanged ones only once to the MinIO bucket
   `opencs-datasets`, recording the sha256 as object metadata.
4. **Mount** — the serving tree is mounted **read-only** into notebook pods at
   `/opt/opencs/datasets`. Dataset loading cells read from that path.

## Rules

- Students can never write to this tree.
- No runtime downloads from Kaggle or public mirrors; the files are served
  locally.
- Every version is immutable. A content change becomes a new version directory.
- `license_status` records whether redistribution has been verified. Datasets
  marked `review-required` must be confirmed before production use.

## Adding a dataset

1. Add a `DatasetSpec` to `scripts/fetch_datasets.py` with the licence,
   attribution and transform description.
2. Run `python scripts/fetch_datasets.py --only <slug> --force`.
3. Run `python scripts/validate_content.py` and `make seed`.

## Licences

Each manifest records `license`, `license_url`, `license_status`,
`source_url` and `attribution`. These are surfaced verbatim in the catalogue
UI; nothing is inferred.
