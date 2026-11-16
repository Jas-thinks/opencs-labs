"""Dataset catalogue API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.datasets.schemas import (
    CategorySummary,
    DatasetDetail,
    DatasetListResponse,
    DatasetSummary,
    DatasetVersionOut,
    PreviewResponse,
    SnippetResponse,
)
from app.datasets.service import DatasetService
from app.db.session import get_db
from app.users.models import User

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _service(db: Session = Depends(get_db)) -> DatasetService:
    return DatasetService(db)


def _summary(dataset) -> DatasetSummary:
    version = dataset.current_version
    return DatasetSummary(
        id=dataset.id,
        slug=dataset.slug,
        title=dataset.title,
        summary=dataset.summary,
        category=dataset.category,
        teaching_tags=dataset.teaching_tags or [],
        version=version.version if version else None,
        format=version.format if version else None,
        row_count=version.row_count if version else None,
        size_bytes=version.size_bytes if version else None,
        license=version.license if version else None,
        license_status=version.license_status if version else None,
    )


@router.get("", response_model=DatasetListResponse)
def list_datasets(
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    tag: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
    _: User = Depends(get_current_user),
    service: DatasetService = Depends(_service),
):
    rows, total = service.list(q=q, category=category, tag=tag, limit=limit, offset=offset)
    return DatasetListResponse(
        datasets=[_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/categories", response_model=list[CategorySummary])
def categories(
    _: User = Depends(get_current_user), service: DatasetService = Depends(_service)
):
    return service.categories()


@router.get("/{slug}", response_model=DatasetDetail)
def dataset_detail(
    slug: str, _: User = Depends(get_current_user), service: DatasetService = Depends(_service)
):
    dataset = service.get(slug)
    version = dataset.current_version
    summary = _summary(dataset)
    return DatasetDetail(
        **summary.model_dump(),
        description=dataset.description,
        attribution=version.attribution if version else "",
        source_url=version.source_url if version else "",
        license_url=version.license_url if version else "",
        columns=version.columns if version else [],
        preview=version.preview if version else [],
        versions=[
            DatasetVersionOut.model_validate(candidate)
            for candidate in sorted(dataset.versions, key=lambda v: v.version, reverse=True)
        ],
        read_only=True,
    )


@router.get("/{slug}/preview", response_model=PreviewResponse)
def dataset_preview(
    slug: str,
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_user),
    service: DatasetService = Depends(_service),
):
    return service.preview(slug, limit=limit)


@router.get("/{slug}/snippet", response_model=SnippetResponse)
def dataset_snippet(
    slug: str,
    version: int | None = Query(default=None, ge=1),
    _: User = Depends(get_current_user),
    service: DatasetService = Depends(_service),
):
    return service.snippet(slug, version)


@router.get("/{slug}/versions", response_model=list[DatasetVersionOut])
def dataset_versions(
    slug: str, _: User = Depends(get_current_user), service: DatasetService = Depends(_service)
):
    dataset = service.get(slug)
    return [
        DatasetVersionOut.model_validate(candidate)
        for candidate in sorted(dataset.versions, key=lambda v: v.version, reverse=True)
    ]
