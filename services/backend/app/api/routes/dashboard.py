"""Role-aware dashboard + health endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentPrincipal
from app.db.session import get_db
from app.models import User
from app.services import jira_service, meeting_service, task_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(principal: CurrentPrincipal, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await db.get(User, uuid.UUID(principal.user_id))
    agenda = await task_service.get_daily_agenda(db, user)
    overdue = await task_service.list_for_user(db, user, overdue=True)
    nxt = await meeting_service.next_for_user(db, user)
    jira = await jira_service.list_for_user(db, user)
    return {
        "today": {"items": len(agenda["items"])},
        "overdue_tasks": overdue["count"],
        "next_meeting": nxt["next"],
        "jira_open": jira["count"],
        "role": principal.role,
    }
