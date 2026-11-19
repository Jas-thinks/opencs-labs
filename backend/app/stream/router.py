"""Course stream endpoints (announcements and materials)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.service import NotebookService
from app.notebooks.uploads import NotebookUpload
from app.stream.schemas import (
    CopyOut,
    NotebookUploadOut,
    PostCreate,
    PostListResponse,
    PostOut,
    PostUpdate,
    ReadersResponse,
)
from app.stream.service import StreamService
from app.users.models import User

router = APIRouter(tags=["stream"])


def _service(db: Session = Depends(get_db)) -> StreamService:
    return StreamService(db)


@router.get("/courses/{course_id}/posts", response_model=PostListResponse)
def list_posts(
    course_id: str,
    kind: str | None = Query(default=None, pattern="^(announcement|material)$"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    data = service.list_posts(user, course_id, kind=kind, cursor=cursor, limit=limit)
    return PostListResponse(posts=[PostOut(**p) for p in data["posts"]], next_cursor=data["next_cursor"])


@router.post("/courses/{course_id}/posts", response_model=PostOut, status_code=201)
def create_post(
    course_id: str,
    payload: PostCreate,
    request: Request,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    enforce_rate_limit(request, "post-create", 30)
    return PostOut(**service.create_post(user, course_id, payload))


@router.get("/posts/{post_id}", response_model=PostOut)
def get_post(
    post_id: str,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    return PostOut(**service.get_post(user, post_id))


@router.patch("/posts/{post_id}", response_model=PostOut)
def update_post(
    post_id: str,
    payload: PostUpdate,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    return PostOut(**service.update_post(user, post_id, payload))


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(
    post_id: str,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    service.delete_post(user, post_id)
    return Response(status_code=204)


@router.post("/posts/{post_id}/read", status_code=204)
def mark_read(
    post_id: str,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    service.mark_read(user, post_id)
    return Response(status_code=204)


@router.get("/posts/{post_id}/readers", response_model=ReadersResponse)
def readers(
    post_id: str,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    return ReadersResponse(**service.readers(user, post_id))


@router.post("/courses/{course_id}/notebook-uploads", response_model=NotebookUploadOut, status_code=201)
def upload_notebook(
    course_id: str,
    payload: NotebookUpload,
    request: Request,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    """Staff upload a .ipynb to attach to a post (kind=notebook, target=sha256)."""
    enforce_rate_limit(request, "notebook-upload", 30)
    return NotebookUploadOut(**service.upload_notebook(user, course_id, payload))


@router.get("/posts/{post_id}/attachments/{attachment_id}/notebook")
def download_attachment(
    post_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    label, sha256, document = service.notebook_document(user, post_id, attachment_id)
    return JSONResponse(
        content=document,
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="{label}"',
            "ETag": f'"{sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/posts/{post_id}/attachments/{attachment_id}/copy", response_model=CopyOut)
def copy_attachment(
    post_id: str,
    attachment_id: str,
    backend: NotebookBackend = Depends(get_notebook_backend),
    user: User = Depends(get_current_user),
    service: StreamService = Depends(_service),
):
    # Same session as the stream service: one unit of work.
    return CopyOut(**service.copy_notebook(user, post_id, attachment_id, NotebookService(service.db, backend)))
