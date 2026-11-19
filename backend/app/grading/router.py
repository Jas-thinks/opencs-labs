"""Assignment, submission and grading endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.grading.schemas import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentOut,
    AssignmentUpdate,
    GradeListResponse,
    GradeOut,
    GradeRequest,
    MyGradeOut,
    MyGradesResponse,
    ReturnResult,
    RubricOut,
    RubricUpsert,
    StartAssignmentOut,
    SubmissionCreate,
    SubmissionDetailOut,
    SubmissionListResponse,
    SubmissionOut,
)
from app.grading.service import GradingService
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.service import NotebookService
from app.notebooks.uploads import NotebookUpload
from app.users.models import User

router = APIRouter(tags=["grading"])


def _service(
    db: Session = Depends(get_db),
    backend: NotebookBackend = Depends(get_notebook_backend),
) -> GradingService:
    return GradingService(db, NotebookService(db, backend))


# -- assignments ---------------------------------------------------------
@router.post(
    "/courses/{course_id}/assignments", response_model=AssignmentOut, status_code=201
)
def create_assignment(
    course_id: str,
    payload: AssignmentCreate,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentOut(**service.create_assignment(user, course_id, payload))


@router.get("/courses/{course_id}/assignments", response_model=AssignmentListResponse)
def list_assignments(
    course_id: str,
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentListResponse(
        assignments=[
            AssignmentOut(**row)
            for row in service.list_assignments(
                user, course_id, include_archived=include_archived
            )
        ]
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentOut)
def get_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentOut(**service.get_assignment(user, assignment_id))


@router.patch("/assignments/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: str,
    payload: AssignmentUpdate,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentOut(**service.update_assignment(user, assignment_id, payload))


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    service.delete_assignment(user, assignment_id)
    return Response(status_code=204)


@router.post("/assignments/{assignment_id}/archive", response_model=AssignmentOut)
def archive_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentOut(**service.set_archived(user, assignment_id, True))


@router.post("/assignments/{assignment_id}/unarchive", response_model=AssignmentOut)
def unarchive_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return AssignmentOut(**service.set_archived(user, assignment_id, False))


@router.post("/assignments/{assignment_id}/start", response_model=StartAssignmentOut)
def start_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return StartAssignmentOut(**service.start_assignment(user, assignment_id))


@router.post("/assignments/{assignment_id}/return", response_model=ReturnResult)
def return_all(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return ReturnResult(returned=service.return_all(user, assignment_id))


# -- rubrics -------------------------------------------------------------
@router.put("/assignments/{assignment_id}/rubric", response_model=RubricOut)
def upsert_rubric(
    assignment_id: str,
    payload: RubricUpsert,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return RubricOut(**service.upsert_rubric(user, assignment_id, payload))


@router.get("/assignments/{assignment_id}/rubric", response_model=RubricOut)
def get_rubric(
    assignment_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return RubricOut(**service.get_rubric(user, assignment_id))


# -- submissions ---------------------------------------------------------
@router.post(
    "/assignments/{assignment_id}/submissions",
    response_model=SubmissionOut,
    status_code=201,
)
def submit(
    assignment_id: str,
    payload: SubmissionCreate,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return SubmissionOut(
        **service.submit(user, assignment_id, payload.notebook_id)
    )


@router.post(
    "/assignments/{assignment_id}/submissions/upload",
    response_model=SubmissionOut,
    status_code=201,
)
def submit_upload(
    assignment_id: str,
    payload: NotebookUpload,
    request: Request,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    """Turn in an .ipynb file from the student's computer (no server needed)."""
    enforce_rate_limit(request, "notebook-upload", 30)
    return SubmissionOut(**service.submit_upload(user, assignment_id, payload))


@router.get(
    "/assignments/{assignment_id}/submissions", response_model=SubmissionListResponse
)
def list_submissions(
    assignment_id: str,
    status: str | None = Query(default=None, pattern="^(submitted|graded|draft|returned)$"),
    late: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    data = service.list_submissions(
        user, assignment_id, status=status, late=late, cursor=cursor, limit=limit
    )
    return SubmissionListResponse(
        submissions=[SubmissionOut(**row) for row in data["submissions"]],
        next_cursor=data["next_cursor"],
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionDetailOut)
def get_submission(
    submission_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return SubmissionDetailOut(**service.get_submission_detail(user, submission_id))


@router.get("/submissions/{submission_id}/notebook")
def submission_notebook(
    submission_id: str,
    request: Request,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    submission, document, sha256, file_stem = service.submission_notebook_file(user, submission_id)
    # Snapshots are immutable and content-addressed: let the browser cache them.
    etag = f'"{sha256}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"}
    if request.headers.get("if-none-match") == etag and not download:
        return Response(status_code=304, headers=headers)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{file_stem}.ipynb"'
    return JSONResponse(content=document, media_type="application/json", headers=headers)


@router.post("/submissions/{submission_id}/grade", response_model=GradeOut)
def grade_submission(
    submission_id: str,
    payload: GradeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    enforce_rate_limit(request, "submission-grade", 60)
    return GradeOut(**service.grade(user, submission_id, payload))


@router.post("/submissions/{submission_id}/return", response_model=GradeOut)
def return_submission(
    submission_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return GradeOut(**service.return_submission(user, submission_id))


@router.get("/submissions/{submission_id}/grades", response_model=GradeListResponse)
def list_grades(
    submission_id: str,
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return GradeListResponse(
        grades=[GradeOut(**row) for row in service.list_grades(user, submission_id)]
    )


# -- student view --------------------------------------------------------
@router.get("/me/grades", response_model=MyGradesResponse)
def my_grades(
    course_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: GradingService = Depends(_service),
):
    return MyGradesResponse(
        grades=[MyGradeOut(**row) for row in service.my_grades(user, course_id)]
    )
