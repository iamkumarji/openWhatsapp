"""Task REST endpoints (portal-facing, JWT + RBAC)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentPrincipal
from app.db.session import get_db
from app.models import AuditLog, Task, TaskAssignment, TaskPriority
from app.schemas import TaskCreate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
async def create_task(
    body: TaskCreate,
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    principal.require("task.create")
    if body.assignee_ids:
        principal.require("task.assign")  # assigning to others needs the stronger perm

    task = Task(
        title=body.title,
        description=body.description,
        priority=TaskPriority(body.priority),
        created_by=uuid.UUID(principal.user_id),
        team_id=uuid.UUID(principal.team_id) if principal.team_id else None,
        due_at=body.due_at,
        rrule=body.rrule,
        escalate_after_hours=body.escalate_after_hours,
    )
    db.add(task)
    await db.flush()

    assignees = body.assignee_ids or [principal.user_id]
    for aid in assignees:
        db.add(TaskAssignment(task_id=task.id, assignee_id=uuid.UUID(aid),
                              assigned_by=uuid.UUID(principal.user_id)))

    db.add(AuditLog(actor_id=uuid.UUID(principal.user_id), action="task.create",
                    entity_type="task", entity_id=task.id,
                    audit_metadata={"assignees": assignees}))
    await db.commit()
    return {"id": str(task.id), "status": task.status.value}


@router.get("")
async def list_tasks(
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = None,
    overdue: bool = False,
    assignee_id: str | None = Query(default=None),
):
    from app.models import User
    from app.services import task_service

    # employees may only query themselves; managers may pass an assignee in their team
    target = assignee_id or principal.user_id
    if target != principal.user_id:
        principal.require("task.view.team")

    user = await db.get(User, uuid.UUID(target))
    if user is None:
        raise HTTPException(404, "user_not_found")
    return await task_service.list_for_user(db, user, status=status, overdue=overdue)


@router.post("/{task_id}/assign")
async def assign_task(
    task_id: uuid.UUID,
    assignee_ids: list[str],
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    principal.require("task.assign")
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task_not_found")
    for aid in assignee_ids:
        db.add(TaskAssignment(task_id=task.id, assignee_id=uuid.UUID(aid),
                              assigned_by=uuid.UUID(principal.user_id)))
    db.add(AuditLog(actor_id=uuid.UUID(principal.user_id), action="task.assign",
                    entity_type="task", entity_id=task.id))
    await db.commit()
    return {"ok": True}
