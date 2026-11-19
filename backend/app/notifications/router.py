"""Current user's notification inbox."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.db.session import get_db
from app.notifications.service import NotificationService
from app.users.models import User

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    course_id: uuid.UUID | None = None
    title: str
    link: str
    created_at: dt.datetime
    read_at: dt.datetime | None = None


class NotificationList(BaseModel):
    notifications: list[NotificationOut]
    next_cursor: str | None = None


class UnreadCount(BaseModel):
    unread: int


class MarkRead(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


def _service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.get("", response_model=NotificationList)
def list_notifications(
    unread: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(_service),
):
    return NotificationList(**service.list(user, unread_only=unread, cursor=cursor, limit=limit))


@router.get("/count", response_model=UnreadCount)
def unread_count(user: User = Depends(get_current_user), service: NotificationService = Depends(_service)):
    return UnreadCount(unread=service.unread_count(user))


@router.post("/read", response_model=UnreadCount)
def mark_read(
    payload: MarkRead,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(_service),
):
    service.mark_read(user, payload.ids)
    return UnreadCount(unread=service.unread_count(user))
