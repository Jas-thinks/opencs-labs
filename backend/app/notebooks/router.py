"""Notebook workspace endpoints."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.core.config import settings
from app.db.session import get_db
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.schemas import (
    AutosaveRequest,
    AutosaveResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    NotebookCreate,
    NotebookListResponse,
    NotebookOut,
    NotebookUpdate,
    NotebookVersionList,
    NotebookVersionOut,
    OpenNotebookResponse,
    ServerStateOut,
)
from app.notebooks.service import NotebookService
from app.users.models import User

logger = logging.getLogger("opencs.notebooks")
router = APIRouter(prefix="/notebooks", tags=["notebooks"])


def _service(db: Session = Depends(get_db), backend: NotebookBackend = Depends(get_notebook_backend)) -> NotebookService:
    return NotebookService(db, backend)


@router.get("/server", response_model=ServerStateOut)
def server_state(user: User = Depends(get_current_user), service: NotebookService = Depends(_service)):
    return service.server_state(user).as_dict()


@router.post("/server/start", response_model=ServerStateOut)
def start_server(
    request: Request,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    enforce_rate_limit(request, "server-start", settings.rate_limit_launch_per_minute)
    return service.start_server(user).as_dict()


@router.post("/server/stop", response_model=ServerStateOut)
def stop_server(user: User = Depends(get_current_user), service: NotebookService = Depends(_service)):
    service.stop_server(user)
    return ServerStateOut(running=False, ready=False, status="stopped")


@router.get("", response_model=NotebookListResponse)
def list_notebooks(user: User = Depends(get_current_user), service: NotebookService = Depends(_service)):
    rows = service.list_owned(user)
    return NotebookListResponse(
        notebooks=[NotebookOut.model_validate(row) for row in rows], total=len(rows)
    )


@router.post("", response_model=NotebookOut, status_code=201)
def create_notebook(
    payload: NotebookCreate,
    request: Request,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    enforce_rate_limit(request, "notebook-create", 30)
    row = service.create(user, title=payload.title)
    return NotebookOut.model_validate(row)


@router.patch("/{notebook_id}", response_model=NotebookOut)
def rename_notebook(
    notebook_id: str,
    payload: NotebookUpdate,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    row = service.rename(user, notebook_id, payload.title)
    return NotebookOut.model_validate(row)


@router.delete("/{notebook_id}", status_code=204)
def delete_notebook(
    notebook_id: str,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    service.delete(user, notebook_id)
    return Response(status_code=204)


@router.get("/{notebook_id}/open", response_model=OpenNotebookResponse)
def open_notebook(
    notebook_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    enforce_rate_limit(request, "notebook-open", settings.rate_limit_launch_per_minute)
    row, url = service.open(user, notebook_id)
    return OpenNotebookResponse(notebook=NotebookOut.model_validate(row), url=url)


@router.get("/{notebook_id}/download")
def download_notebook(
    notebook_id: str,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    row, content = service.download(user, notebook_id)
    body = json.dumps(content, indent=1, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/x-ipynb+json",
        headers={"content-disposition": f'attachment; filename="{row.file_name}"'},
    )


@router.put("/{notebook_id}/autosave", response_model=AutosaveResponse)
def autosave_notebook(
    notebook_id: str,
    payload: AutosaveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    enforce_rate_limit(
        request,
        f"notebook-autosave:{notebook_id}",
        settings.rate_limit_autosave_per_minute,
    )
    result = service.autosave(
        user,
        notebook_id,
        base_version=payload.base_version,
        document=payload.document,
    )
    return AutosaveResponse(**result)


@router.post("/{notebook_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    notebook_id: str,
    payload: HeartbeatRequest | None = None,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    client = payload.client if payload else "jupyterlab"
    return HeartbeatResponse(**service.heartbeat(user, notebook_id, client=client))


@router.get("/{notebook_id}/versions", response_model=NotebookVersionList)
def list_versions(
    notebook_id: str,
    kind: str | None = Query(default=None, pattern="^(autosave|checkpoint|submission|manual)$"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    rows = service.list_versions(user, notebook_id, kind=kind, limit=limit)
    return NotebookVersionList(
        versions=[NotebookVersionOut(**row) for row in rows]
    )


@router.get("/{notebook_id}/versions/{version_number}/download")
def download_version(
    notebook_id: str,
    version_number: int,
    user: User = Depends(get_current_user),
    service: NotebookService = Depends(_service),
):
    row, version, document = service.download_version(user, notebook_id, version_number)
    body = json.dumps(document, indent=1, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/x-ipynb+json",
        headers={
            "content-disposition": (
                f'attachment; filename="{row.file_name.removesuffix(".ipynb")}'
                f'-v{version["version_number"]}.ipynb"'
            )
        },
    )
