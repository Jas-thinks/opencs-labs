# OpenCS Labs -- dataset storage and lifecycle

Datasets are the one part of the platform where "just download it in the
notebook" is explicitly forbidden (HLD 10.1, FR-045). If 400 concurrent
students each fetched Iris from UCI at kernel start, the platform would be
network-bound on somebody else's server and would break the moment a source
went offline. Every dataset is therefore fetched **once**, verified, published
to object storage, and materialised onto a read-only shared volume that
notebook pods mount.

## The lifecycle

```
  datasets/raw/            datasets/manifests/          MinIO                    PVC                       notebook pods
       |                         |                       |                       |                            |
  1 raw      -- fetch_datasets.py --  2 manifests   -- sync_datasets.py --  3 upload  -- materialise --  4 serving tree  -- 5 ro mount
       |                         |                       |                       |                            |
  as downloaded            sha256 + columns          bucket                 /opt/opencs/datasets         readOnly: true
  (git-ignored)           + licence + preview      opencs-datasets            (RWX, uid/gid 1000)          inside every pod
```

### 1. Raw acquisition -- `scripts/fetch_datasets.py`

Downloads each source exactly once, normalises it into a stable file name,
samples oversized tables to a documented row count, and writes the result under
`datasets/raw/` (git-ignored: these are large binaries with their own licences).

```bash
# From the repository root, with the backend venv active:
make fetch-datasets

# Equivalent:
backend/.venv/bin/python scripts/fetch_datasets.py

# Targeted refresh of specific datasets:
backend/.venv/bin/python scripts/fetch_datasets.py --only iris,titanic

# Force re-download even when the raw file already exists:
backend/.venv/bin/python scripts/fetch_datasets.py --force --only titanic
```

Rules the script obeys, and that you must not work around:

- **Nothing is invented.** Every manifest value (sha256, row count, column
  dtypes, size) is computed from the file on disk. If a value is unknown, it is
  absent, not guessed.
- **Licence provenance is recorded**, including `license_status`. A dataset with
  `license_status: review-required` must not be published to students until a
  human signs it off. Check `datasets/manifests/index.json`.
- **No runtime downloads.** The notebook image never fetches a dataset.

### 2. Verification -- sha256 and manifests

`scripts/fetch_datasets.py` writes one manifest per dataset
(`datasets/manifests/<slug>.json`) plus an index (`datasets/manifests/index.json`)
summarising every slug/version/hash.

```bash
# Validate the whole manifest set against the files on disk. This is exactly
# what the publish step does before uploading, so running it alone is a safe
# dry check (--skip-upload = verify the serving tree, upload nothing):
backend/.venv/bin/python scripts/sync_datasets.py --skip-upload

# Or verify a single file by hand:
sha256sum datasets/serving/iris/v1/iris.csv
#   c52742e50315a99f956a383faedf7575552675f6409ef0f9a47076dd08479930  datasets/serving/iris/v1/iris.csv
python3 -c "
import json
m = json.load(open('datasets/manifests/iris.json'))
v = m['versions'][0]
print(v['sha256'], v['size_bytes'], v['relative_mount_path'])
"
```

A hash mismatch is a hard stop: it means the source changed or the file was
corrupted, and the catalogue must not advertise bytes it has not verified. The
backend re-validates every manifest at load time
(`backend/app/datasets/manifests.py` rejects bad hashes, path traversal and
unsupported formats) so a malformed manifest can never reach a student.

The manifest schema (see `datasets/manifests/iris.json` for a real example):

```json
{
  "dataset_id": "iris",
  "versions": [
    {
      "version": 1,
      "format": "csv",
      "object_key": "iris/v1/iris.csv",
      "relative_mount_path": "iris/v1/iris.csv",
      "sha256": "c52742e50315a99f956a383faedf7575552675f6409ef0f9a47076dd08479930",
      "size_bytes": 3858,
      "row_count": 150,
      "columns": [{"name": "sepal_length", "dtype": "float64"}],
      "license": "CC BY 4.0",
      "read_only": true
    }
  ]
}
```

### 3. Upload to MinIO -- `scripts/sync_datasets.py`

MinIO is the canonical object store (bucket `opencs-datasets`). Object keys are
`<slug>/v<version>/<file>`, which keeps versions immutable: publishing v2 never
overwrites v1, so an exercise that pinned v1 still resolves.

```bash
# Default: verify every manifest, then upload changed files to MinIO.
# Idempotent -- identical bytes are detected by the remote sha256 metadata and
# skipped, so re-running after adding one dataset uploads only that dataset.
make sync-datasets
backend/.venv/bin/python scripts/sync_datasets.py

# Re-upload even when the remote copy already matches:
backend/.venv/bin/python scripts/sync_datasets.py --force

# Inspect what landed in the bucket:
mc alias set opencs http://minio:9000 "$OPENCE_S3_ACCESS_KEY" "$OPENCE_S3_SECRET_KEY"
mc ls --recursive opencs/opencs-datasets
```

The bucket is created by the `minio-init` Job
(`infrastructure/kubernetes/minio.yaml`) and is private: `mc anonymous set none`.
No anonymous read, no public dataset URL. Notebook pods never talk to MinIO at
all -- see step 5.

### 4. Materialise the read-only serving tree

Students read from a POSIX path, not from an S3 endpoint
(`/opt/opencs/datasets/iris/v1/iris.csv`). The serving tree must therefore be
present on a POSIX volume, with every file matching the sha256 its manifest
records.

`scripts/sync_datasets.py` handles **upload + verification** and, when run with
the default environment, also keeps the local `datasets/serving/` tree in place
for development. Materialising a *cluster* volume is the job of the
`datasets-sync` Job in `infrastructure/kubernetes/datasets-pvc.yaml`, which
mounts the `opencs-datasets` PVC at `/opt/opencs/datasets` and runs both halves:

| `DATASETS_SYNC_MODE` | Behaviour |
| --- | --- |
| `all` (default) | Upload `datasets/serving` to MinIO if it is present in the image, then download every published object onto the PVC and verify sha256. |
| `upload` | Upload only. Fails loudly if `datasets/serving` is absent, rather than publishing nothing. |
| `materialise` | Assume the bucket is already populated and only build the PVC tree. This is the mode to use from a backend image that ships manifests but not the git-ignored `datasets/serving` payload. |

Note that `datasets/serving/` is git-ignored and is not part of the backend
image, so a fresh cluster normally runs `materialise` against a bucket that CI
populated with `upload`.

```bash
kubectl -n opencs delete job datasets-sync --ignore-not-found
kubectl apply -f infrastructure/kubernetes/datasets-pvc.yaml
kubectl -n opencs wait --for=condition=complete job/datasets-sync --timeout=1800s
kubectl -n opencs logs job/datasets-sync --tail=50

# Mode is an env var on the Job container; override it per run:
kubectl -n opencs set env job/datasets-sync DATASETS_SYNC_MODE=materialise
```

Locally (development) no PVC is involved: `datasets/serving/` is the serving
tree the backend reads when running outside the cluster.

Resulting layout:

```
/opt/opencs/datasets/
├── iris/
│   └── v1/
│       ├── iris.csv
│       └── manifest.json
├── titanic/
│   └── v1/
│       ├── titanic.csv
│       └── manifest.json
└── ...
```

### 5. Mount read-only into notebook pods

The PVC is mounted with `readOnly: true` in every single-user pod
(KubeSpawner `extraVolumes`/`extraVolumeMounts`, see
`infrastructure/helm/opencs/values.yaml`), and the backend reads the same tree:

- `OPENCE_DATASET_MOUNT_PATH=/opt/opencs/datasets` -- what the student's kernel
  sees, and what the generated loading cell hard-codes.
- `OPENCE_DATASET_SERVING_DIR=/opt/opencs/datasets` -- what the backend reads for
  previews and snippet generation.

Verify from inside a notebook pod as uid 1000:

```bash
kubectl -n opencs-hub exec -it <student-pod> -- \
  python -c "import pandas as pd; print(pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv').shape)"
```

The read-only mount is the enforcement point for FR-047: a student can copy a
dataset into their own home to modify it, but cannot alter the shared tree. The
matching admission control is rule (b) of
`infrastructure/policies/kyverno-notebook-policy.yaml`.

## Access-mode trade-off (RWX vs RWO vs ROX)

| Mode | Use here | Reality |
| --- | --- | --- |
| `ReadWriteMany` | **the serving PVC** | One writer (`datasets-sync`) and up to 450 readers across many nodes. Requires a shared-filesystem StorageClass (NFS/EFS/CephFS/Longhorn RWX) -- see `storageclass-rwx.yaml`. Adds a network hop and a storage-server dependency, and RWX gives no useful POSIX locking guarantees. That is acceptable for an append-free, write-once tree. |
| `ReadOnlyMany` | **not used** | Deprecated in the PersistentVolume API and unsupported by most modern CSI drivers. `ReadWriteMany` + `readOnly: true` mounts gives the same protection. |
| `ReadWriteOnce` | per-student home PVCs | Per-node at best; mounting a RWO volume into pods on different nodes is not portable, so it cannot back 400 concurrent notebook pods. Used only for the notebook home directories and for PostgreSQL/MinIO data. |

If your cluster has no RWX class, the fallback is a per-node cache: an
initContainer (or a DaemonSet seeder) copies the tree from MinIO onto a
`hostPath` under `/opt/opencs/cache` on each notebook node, and KubeSpawner
mounts that path read-only. That is what the Kyverno hostPath exception in rule
(b) exists for. It costs a full copy per node and needs a cache-busting
strategy, so prefer RWX when it is available.

## Adding or updating a dataset

1. Confirm the licence permits redistribution for teaching, and record the
   source and attribution in the dataset spec inside
   `scripts/fetch_datasets.py`.
2. `make fetch-datasets` (this computes the new sha256 and manifest).
3. Review the manifest diff: `git diff datasets/manifests/`.
4. Publish: `make sync-datasets`, then re-run the `datasets-sync` Job in-cluster.
5. Seed/refresh the catalogue row so the UI can see it: `make seed`.
6. Verify in a notebook that the generated snippet path resolves and reads.

Never edit a file under `datasets/serving/` by hand and never bump
`size_bytes`/`sha256` in a manifest by hand -- both are regenerated from the
actual bytes, and a hand-edit will be rejected by
`backend/app/datasets/manifests.py` at load time.

## Backup and recovery

- MinIO holds the canonical objects: back up the bucket (versioning plus a
  scheduled mirror to a second destination), and test a restore.
- The serving PVC is **derived data**: it can be rebuilt at any time by
  re-running the `datasets-sync` Job. Do not back it up, and do not treat it as
  a source of truth.
- Per-student notebook homes are *not* derived: they need their own backup
  policy (see `docs/OPERATIONS.md`).
