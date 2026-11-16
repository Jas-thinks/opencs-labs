# @opencs/jupyterlab-datasets

JupyterLab extension that inserts an OpenCS dataset loading cell into the active
notebook — **and never executes it**.

Implements [ADR-005](../../docs/ADR/005-dataset-cell-insertion.md) and
[ADR-008](../../docs/ADR/006-jupyterlab-extension.md).

## The contract

```ts
// src/index.ts — the only place a cell is created
if (snippet.auto_execute) {
  throw new Error('OpenCS never inserts executable-on-insert cells.');
}
insertCodeCell(tracker, snippet.code);
```

- `requestExecute` appears **nowhere** in this extension.
- The backend returns `auto_execute: false`; the extension *also* refuses
  `true`, so a backend regression cannot silently run student code.
- The inserted cell is a plain, readable `pd.read_csv(...)` + `df.head()`.

## What it adds

An **OpenCS** menu with:

| Item | Effect |
|---|---|
| Open dataset catalogue | A panel listing published datasets (title, category, format, rows, licence) |
| Insert dataset cell | Fetches the snippet for the chosen dataset and inserts it below the active cell |

The panel fetches `GET {apiBase}/datasets` with `credentials: 'include'`, so the
student's existing OpenCS session cookie authorises it — no separate token.

## Configure

The API base defaults to `/api/v1`. Override it in **Settings → Settings Editor →
OpenCS Datasets → API base path** (schema in `schema/plugin.json`).

## Build

```bash
npm install --include=dev
npm run build          # tsc → lib/, then `jupyter labextension build`
```

## Install into an environment

```bash
# From this directory, into the Python environment that runs JupyterLab:
pip install -e .               # only if you also ship a Python package
# or link a built extension:
jupyter labextension develop . --overwrite
jupyter labextension list      # should list @opencs/jupyterlab-datasets
```

For a production notebook image, build the extension in a separate stage and
install the prebuilt artifact into the image's `labextensions` directory rather
than shipping TypeScript.

## Test manually

1. Open a notebook.
2. **OpenCS → Open dataset catalogue**.
3. Press **Insert cell** on *Iris*.
4. A new code cell appears containing `pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv')`.
5. The cell is **not** executed — no output appears until you press Run.
