"""Helpers for constructing and validating .ipynb documents.

Only server-generated names are ever used for storage paths.
"""

from __future__ import annotations

import re
import unicodedata

import nbformat

from app.core.config import settings

NOTEBOOK_SUFFIX = ".ipynb"
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]+")
_MAX_STEM = 90
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
CONTAINER_DATASET_PREFIX = "/opt/opencs/datasets"


def validate_document(document: object) -> dict:
    """Return ``document`` if it is a structurally valid .ipynb v4 document.

    Raises ``ValueError`` for anything that is not a notebook; the API layer
    turns that into a 422/400 response. The size cap protects the database
    from oversized autosave payloads.
    """
    if not isinstance(document, dict):
        raise ValueError("notebook document must be a JSON object")
    if document.get("nbformat") != 4:
        raise ValueError("notebook document must use nbformat 4")
    if not isinstance(document.get("cells"), list):
        raise ValueError("notebook document must contain a cells array")
    import json

    encoded = json.dumps(document, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_DOCUMENT_BYTES:
        raise ValueError("notebook document is too large")
    try:
        import warnings

        notebook = nbformat.from_dict(document)
        # Normalise first so notebooks authored before cell ids existed are
        # still accepted, then validate the normalised copy.
        from nbformat.validator import normalize

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _, notebook = normalize(notebook)
        nbformat.validate(notebook)
    except nbformat.ValidationError as exc:
        raise ValueError(f"invalid notebook document: {exc.message}") from exc
    return document


def localize_source(source: str) -> str:
    """Point authored ``/opt/opencs/datasets`` literals at the configured path.

    Lesson and exercise content is authored against the container mount. When
    the backend runs on the host with ``OPENCE_DATASET_MOUNT_PATH`` set to the
    repo's serving tree, generated cells must read from that path instead. In
    container deployments the two paths are identical and this is a no-op.
    """
    mount = (settings.dataset_mount_path or "").rstrip("/")
    if mount and mount != CONTAINER_DATASET_PREFIX:
        return source.replace(CONTAINER_DATASET_PREFIX, mount)
    return source


def validate_file_name(name: str) -> str:
    """Validate a server-generated notebook file name.

    Rejects traversal, separators, hidden files and non-.ipynb names.
    """
    if not name or len(name) > 160:
        raise ValueError("invalid notebook file name")
    if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise ValueError("invalid notebook file name")
    if not name.endswith(NOTEBOOK_SUFFIX) or name == NOTEBOOK_SUFFIX:
        raise ValueError("notebook file name must end with .ipynb")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()\-]*\.ipynb", name):
        raise ValueError("notebook file name contains unsupported characters")
    return name


def slugify_stem(title: str) -> str:
    normalised = unicodedata.normalize("NFKC", title or "").strip()
    stem = _UNSAFE.sub("", normalised).strip(" ._-")
    stem = re.sub(r"\s+", " ", stem)
    if not stem:
        stem = "Untitled Notebook"
    return stem[:_MAX_STEM].strip() or "Untitled Notebook"


def unique_file_name(title: str, existing: set[str] | None = None) -> str:
    stem = slugify_stem(title)
    taken = {name.lower() for name in (existing or set())}
    candidate = f"{stem}{NOTEBOOK_SUFFIX}"
    index = 2
    while candidate.lower() in taken:
        candidate = f"{stem} {index}{NOTEBOOK_SUFFIX}"
        index += 1
    return validate_file_name(candidate)


def code_cell(source: str, *, metadata: dict | None = None) -> dict:
    cell = nbformat.v4.new_code_cell(localize_source(source))
    cell["execution_count"] = None
    cell["outputs"] = []
    if metadata:
        cell["metadata"].update(metadata)
    return cell


def markdown_cell(source: str) -> dict:
    return nbformat.v4.new_markdown_cell(source)


def build_notebook(
    *,
    title: str,
    cells: list[dict] | None = None,
    metadata: dict | None = None,
) -> dict:
    nb = nbformat.v4.new_notebook()
    nb["cells"] = cells or []
    nb["metadata"].update(
        {
            "kernelspec": {
                "display_name": "Python 3 (OpenCS Analytics)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.11"},
            "opencs": {"title": title, "schema": 1},
        }
    )
    if metadata:
        nb["metadata"]["opencs"].update(metadata)
    return nb


def cells_from_sources(
    sources: list[str] | None,
    *,
    intro_markdown: str | None = None,
    metadata: dict | None = None,
) -> list[dict]:
    cells: list[dict] = []
    if intro_markdown:
        cells.append(markdown_cell(intro_markdown))
    for source in sources or []:
        if source.lstrip().startswith(("#", "<!--")) and source.count("\n") > 0 and not _looks_like_code(source):
            cells.append(markdown_cell(source))
        else:
            cells.append(code_cell(source, metadata=metadata))
    return cells


def _looks_like_code(source: str) -> bool:
    markers = ("import ", "from ", "df", "print(", "=", "def ", "plt.", "pd.", "np.")
    first = source.strip().splitlines()[0] if source.strip() else ""
    return any(marker in first for marker in markers)


def extract_code_cells(notebook: dict) -> list[str]:
    return [
        cell.get("source", "")
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
